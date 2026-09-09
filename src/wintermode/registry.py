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
import logging
import re
import sys
from pathlib import Path
from typing import Any

from wintermode import schema

log = logging.getLogger(__name__)

MODULES_DIR = Path(__file__).parent / "modules"
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

REQUIRED_ATTRS = ("id", "title", "interval", "config_schema", "actions")
REQUIRED_METHODS = ("render", "on_tap", "status_items", "on_action")

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
        module_path = entry / "module.py"
        if not module_path.is_file():
            log.warning("registry: %s has no module.py", entry.name)
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"wintermode.modules.{entry.name}.module", module_path
            )
            imported = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(imported)
            module_obj = getattr(imported, "MODULE", None)
        except Exception:
            log.exception("registry: failed to import module %s", entry.name)
            continue
        if module_obj is None or not _looks_like_module(module_obj):
            log.warning("registry: %s has no valid MODULE, skipping", entry.name)
            continue
        if getattr(module_obj, "id", None) != entry.name:
            log.warning(
                "registry: %s's id (%r) does not match its directory, skipping",
                entry.name, getattr(module_obj, "id", None),
            )
            continue
        sys.modules[spec.name] = imported
        found.append(module_obj)
    return found


def _looks_like_module(obj: Any) -> bool:
    return all(hasattr(obj, attr) for attr in REQUIRED_ATTRS) and all(
        callable(getattr(obj, method, None)) for method in REQUIRED_METHODS
    )


class Registry:
    def __init__(self, modules: list[Any], config) -> None:
        self._all = {module.id: module for module in modules}
        self.config = config
        self.refresh()

    def refresh(self) -> None:
        """Re-read enabled/order from config; heal the array."""
        configured = self.config.data.get("modules", [])
        enabled = [mid for mid in configured if mid in self._all]
        for mid in self._all:  # discovered but not configured: enable
            if mid not in enabled:
                enabled.append(mid)
        if enabled != configured:
            self.config.update({"modules": enabled})
        self._enabled = enabled

    def home_order(self) -> list[Any]:
        ids = list(self._enabled)
        if SETTINGS_ID in ids:
            ids.remove(SETTINGS_ID)
            ids.insert(0, SETTINGS_ID)  # settings pinned first
        return [self._all[mid] for mid in ids]

    def enabled_ids(self) -> list[str]:
        return list(self._enabled)

    def get(self, module_id: str) -> Any | None:
        return self._all.get(module_id)

    def __getitem__(self, module_id: str) -> Any:
        return self._all[module_id]

    def __contains__(self, module_id: str) -> bool:
        return module_id in self._all

    def validate_namespaces(self) -> None:
        """Run every module's config_schema over its config namespace."""
        changed = False
        for module in self._all.values():
            if not module.config_schema:
                continue
            current = self.config.data.get(module.id, {})
            valid = schema.validate(module.config_schema, current)
            if valid != current:
                self.config.data[module.id] = valid
                changed = True
        if changed:
            self.config.save()
