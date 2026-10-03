"""Module discovery and the enabled/order bookkeeping.

Modules are plain objects — one directory per module under
`wintermode/modules/<id>/` with a `module.py` defining a module-level
`MODULE`.  The id must match the directory name.  Enabled set and order
come from `config["modules"]`; unknown ids are ignored and missing ids
are appended (the file self-heals).  The settings module is always
pinned first on the home grid.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
from pathlib import Path
from typing import Any

from wintermode import schema
from wintermode.config import RESERVED

log = logging.getLogger(__name__)

MODULES_DIR = Path(__file__).parent / "modules"
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

REQUIRED_ATTRS = ("id", "title", "interval", "config_schema", "actions")
REQUIRED_METHODS = ("render", "on_tap", "on_action")
# `status_items` is OPTIONAL: defining it advertises status-bar content
# (see Registry.statusbar_ids).  A module with nothing to publish simply
# doesn't define it — or sets it to None, like `config_schema = None`.

SETTINGS_ID = "settings"


def discover(base: Path = MODULES_DIR) -> list[Any]:
    """Import every modules/<id>/module.py that looks like a module."""
    found: list[Any] = []
    if not base.is_dir():
        log.warning("registry: no modules directory at %s", base)
        return found
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not ID_RE.match(entry.name):
            log.warning("registry: skipping %s (invalid module id)", entry.name)
            continue
        if entry.name in RESERVED:
            # a module's id IS its config namespace, so a reserved id would
            # overwrite a device key (e.g. "theme" -> a dict -> boot crash)
            log.warning("registry: skipping %s (reserved config key)", entry.name)
            continue
        module_path = entry / "module.py"
        if not module_path.is_file():
            log.warning("registry: %s has no module.py", entry.name)
            continue
        spec = None
        try:
            spec = importlib.util.spec_from_file_location(
                f"wintermode.modules.{entry.name}.module", module_path
            )
            imported = importlib.util.module_from_spec(spec)
            # register BEFORE exec: class decorators (dataclasses etc.)
            # look the module up in sys.modules while the body runs
            sys.modules[spec.name] = imported
            assert spec.loader is not None
            spec.loader.exec_module(imported)
            module_obj = getattr(imported, "MODULE", None)
        except Exception:
            # a module whose body raised is half-initialised: leave nothing
            # in sys.modules, or the next import of that name gets the wreck
            sys.modules.pop(getattr(spec, "name", ""), None)
            log.exception("registry: failed to import module %s", entry.name)
            continue
        if module_obj is None or not _looks_like_module(module_obj):
            log.warning("registry: %s has no valid MODULE, skipping", entry.name)
            continue
        bar = getattr(module_obj, "status_items", None)
        if bar is not None and not callable(bar):
            # a typo'd method must not silently hide the module's bar
            # content — same reject-the-module rule as any other contract
            # violation (None is fine: it means "does not advertise")
            log.warning(
                "registry: %s has a non-callable status_items, skipping",
                entry.name,
            )
            continue
        if inspect.iscoroutinefunction(bar):
            # the bar calls status_items synchronously (items.extend),
            # so an async def would raise TypeError on every bar draw
            log.warning(
                "registry: %s has an async status_items, skipping",
                entry.name,
            )
            continue
        if getattr(module_obj, "id", None) != entry.name:
            log.warning(
                "registry: %s's id (%r) does not match its directory, skipping",
                entry.name, getattr(module_obj, "id", None),
            )
            continue
        found.append(module_obj)
    return found


def _looks_like_module(obj: Any) -> bool:
    """An INSTANCE speaking the contract — a class is not a module.

    `hasattr`/`callable` are both true for the class itself, so
    `MODULE = MyClock` (forgetting the `()`) used to be accepted and
    every method was then called unbound: the app died on the first bar
    draw with a TypeError pointing nowhere near the real mistake.
    """
    if inspect.isclass(obj):
        return False
    return all(hasattr(obj, attr) for attr in REQUIRED_ATTRS) and all(
        callable(getattr(obj, method, None)) for method in REQUIRED_METHODS
    )


class Registry:
    def __init__(self, modules: list[Any], config) -> None:
        self._all = {module.id: module for module in modules}
        self.config = config
        self.refresh()

    def refresh(self) -> None:
        """Re-read enabled/order from config; heal the array and the
        status-bar toggles."""
        configured = self.config.data.get("modules", [])
        enabled = [mid for mid in configured if mid in self._all]
        for mid in self._all:  # discovered but not configured: enable
            if mid not in enabled:
                enabled.append(mid)
        if enabled != configured:
            self.config.update({"modules": enabled})
        self._enabled = enabled
        self._heal_statusbar()

    def _heal_statusbar(self) -> None:
        """Drop status-bar toggles for modules that no longer advertise.

        Compared against the BASE file's map, not the merged view — a
        stale key in the gitignored overlay must not make this rewrite
        the tracked file on every boot.  Like the modules heal, a module
        that failed to import this boot loses its toggle (its id is not
        in `self._all`).
        """
        ids = set(self.statusbar_ids())
        base = self.config.namespace("statusbar", local=False)
        cleaned = {key: enabled for key, enabled in base.items()
                   if key in ids}
        if cleaned != base:
            self.config.set("statusbar", cleaned)

    def home_order(self) -> list[Any]:
        ids = list(self._enabled)
        if SETTINGS_ID in ids:
            ids.remove(SETTINGS_ID)
            ids.insert(0, SETTINGS_ID)  # settings pinned first
        return [self._all[mid] for mid in ids]

    def statusbar_modules(self) -> list[Any]:
        """Modules that advertise status-bar content, in home order.

        The optional `status_items` method IS the advertisement: a module
        with nothing to publish simply doesn't define it, and gets
        neither a STATUS BAR toggle nor bar time.  Computed live — a
        module swapped into the registry mid-run is reflected here.
        Returns the module objects home_order already resolved, so a
        caller never re-indexes the registry by a module-supplied id.
        """
        return [module for module in self.home_order()
                if callable(getattr(module, "status_items", None))]

    def statusbar_ids(self) -> list[str]:
        """Ids of the advertising modules, in home order."""
        return [module.id for module in self.statusbar_modules()]

    def enabled_ids(self) -> list[str]:
        return list(self._enabled)

    def get(self, module_id: str) -> Any | None:
        return self._all.get(module_id)

    def __getitem__(self, module_id: str) -> Any:
        return self._all[module_id]

    def __contains__(self, module_id: str) -> bool:
        return module_id in self._all

    def validate_namespaces(self) -> None:
        """Run every module's config_schema over its config namespace.

        Healing writes back what changed, but local (secret) fields go
        to the overlay — the tracked file never receives them.  Each side
        is compared against the file it is written to, so a repair is not
        shadowed by the other file (and is not re-written every boot).
        """
        patches = {}
        local_patches = {}
        for module in self._all.values():
            if not module.config_schema:
                continue
            base = self.config.namespace(module.id)
            overlay = self.config.namespace(module.id, local=True)
            valid = schema.validate(module.config_schema, {**base, **overlay})
            local_fields = {key: valid[key] for key, field in
                            module.config_schema.items()
                            if key in valid and field.get("local")
                            and (key in base or key in overlay)}
            normal = {key: value for key, value in valid.items()
                      if key not in local_fields}
            if normal != {key: base.get(key) for key in normal}:
                patches[module.id] = normal
            if local_fields and local_fields != {key: overlay.get(key)
                                                 for key in local_fields}:
                local_patches[module.id] = local_fields
        if patches:
            self.config.update(patches)
        if local_patches:
            self.config.update_local(local_patches)
