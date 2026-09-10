"""config.json: defaults-merged, atomically written, live-reloadable.

Writes go through a temp file + os.replace under a lock, so a crash
mid-write can never truncate the config.  Every save bumps `generation`;
the main loop watches it to reload live.  Reserved top-level keys are
validated here; per-module namespaces are validated by the registry
against each module's config_schema.

Secrets: `config.json` is the tracked template with defaults only.  A
gitignored `config.local.json` alongside it holds local overrides
(addresses, API keys — anything a schema marks `"local": true`); it is
deep-merged over the base at load, and `Config.save()` never writes
those values back into the tracked file.
"""

from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from wintermode import schema

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "modules": [],
    "statusbar": {},
    "statusbar_rotate": 10,
    "display": {"mode": "always_on", "idle_seconds": 60,
                "light_from": "07:00", "light_to": "19:00"},
}

RESERVED = {"theme", "modules", "statusbar", "statusbar_rotate", "display"}

# the reserved keys, expressed in the same DSL everything else uses
THEME_SCHEMA = {
    "theme": {"type": "choice", "options": ["dark", "light", "auto"],
              "default": "dark"},
}
ROTATE_SCHEMA = {
    "statusbar_rotate": {"type": "int", "min": 0, "max": 3600,
                         "default": 10},
}
DISPLAY_SCHEMA = {
    "mode": {"type": "choice", "options": ["always_on", "wake_on_touch"],
             "default": "always_on"},
    "idle_seconds": {"type": "int", "min": 5, "max": 3600, "default": 60},
    "light_from": {"type": "time", "default": "07:00"},
    "light_to": {"type": "time", "default": "19:00"},
}

# one settings page for everything display-related: the theme choice,
# the auto-schedule window (only while theme is "auto"), and the
# always-on vs wake-on-touch behavior
DISPLAY_PAGE_SCHEMA = {
    **THEME_SCHEMA,
    "light_from": {"type": "time", "title": "Light from", "default": "07:00",
                   "visible_if": {"field": "theme", "equals": "auto"}},
    "light_to": {"type": "time", "title": "Light to", "default": "19:00",
                 "visible_if": {"field": "theme", "equals": "auto"}},
    "mode": DISPLAY_SCHEMA["mode"],
    # the idle timeout only matters for wake_on_touch
    "idle_seconds": {**DISPLAY_SCHEMA["idle_seconds"],
                     "visible_if": {"field": "mode",
                                    "equals": "wake_on_touch"}},
}


def _deep_update(target: dict, source: dict) -> dict:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _coerce_modules(value: Any) -> list[str]:
    if not isinstance(value, list):
        log.warning("config: 'modules' must be a list, using defaults")
        return []
    return [item for item in value if isinstance(item, str)]


def _coerce_statusbar(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        log.warning("config: 'statusbar' must be an object, using defaults")
        return {}
    # through the schema, so "false"/"no"/"0" from a hand-edit mean off
    return {
        key: schema.coerce_bool(enabled)
        for key, enabled in value.items() if isinstance(key, str)
    }


class Config:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.local_path = self.path.with_name(self.path.stem + ".local.json")
        self._lock = threading.Lock()
        self.generation = 0
        self._healed = False  # the file needed repair while loading
        self._base: dict[str, Any] = self._load(self.path)
        self._local: dict[str, Any] = self._load_local()
        self.data: dict[str, Any] = self._merged()
        if not self.path.exists():
            log.info("config: no %s, writing defaults", self.path)
            self.save()
        elif self._healed:
            # healing in memory only would be re-applied on every boot;
            # write the repaired file so the repair sticks
            log.info("config: rewriting %s with healed values", self.path)
            self.save()

    # --- loading -----------------------------------------------------------

    def _load(self, path: Path) -> dict[str, Any]:
        data = deepcopy(DEFAULTS)
        raw: Any = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text())
            except (OSError, ValueError):
                log.warning("config: unreadable %s, using defaults", path)
                self._healed = True
                raw = {}
            if not isinstance(raw, dict):
                log.warning("config: %s is not an object, using defaults",
                            path)
                self._healed = True
                raw = {}
            _deep_update(data, raw)
        data.update(schema.validate(THEME_SCHEMA, data))
        data.update(schema.validate(ROTATE_SCHEMA, data))
        data["display"] = schema.validate(DISPLAY_SCHEMA, data.get("display"))
        data["modules"] = _coerce_modules(data.get("modules"))
        data["statusbar"] = _coerce_statusbar(data.get("statusbar"))
        # a key the file DID set but the schema had to change is a
        # repair; merely filling in absent keys is not
        if any(data.get(key) != value for key, value in raw.items()):
            self._healed = True
        return data

    def _load_local(self) -> dict[str, Any]:
        """The gitignored overlay: unreadable or absent means empty."""
        if not self.local_path.exists():
            return {}
        try:
            raw = json.loads(self.local_path.read_text())
        except (OSError, ValueError):
            log.warning("config: unreadable %s, ignoring", self.local_path)
            return {}
        if not isinstance(raw, dict):
            log.warning("config: %s is not an object, ignoring",
                        self.local_path)
            return {}
        return raw

    def _merged(self) -> dict[str, Any]:
        merged = deepcopy(self._base)
        _deep_update(merged, self._local)
        return merged

    def _refresh(self) -> None:
        self.data = self._merged()

    # --- writing -----------------------------------------------------------

    def _write(self, path: Path, payload: dict) -> bool:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2) + "\n")
            tmp.replace(path)
        except OSError:
            log.warning("config: could not write %s (read-only?)", path)
            return False
        return True

    def save(self) -> None:
        """Write the tracked base file — local values never leak into it."""
        with self._lock:
            if self._write(self.path, self._base):
                self.generation += 1

    def save_local(self) -> None:
        """Write the gitignored overlay only."""
        with self._lock:
            if self._write(self.local_path, self._local):
                self.generation += 1

    # --- mutation ----------------------------------------------------------

    def update(self, mapping: dict[str, Any]) -> None:
        """Deep-merge top-level namespaces into the base file."""
        with self._lock:
            _deep_update(self._base, mapping)
        self._refresh()
        self.save()

    def update_local(self, mapping: dict[str, Any]) -> None:
        """Deep-merge into the overlay: the home for local-only secrets."""
        with self._lock:
            _deep_update(self._local, mapping)
        self._refresh()
        self.save_local()

    def update_module(self, module_id: str, values: dict,
                      spec: dict | None = None) -> dict:
        """Merge `values` into a module namespace, saved and generation-bumped.

        Pass `spec` (the module's own config_schema) and the merged
        namespace is validated first.  Without it a write can persist a
        value the schema forbids, which the next boot silently clamps —
        and a clamped counter then steps the wrong way at its bound.
        Returns the values actually stored.
        """
        with self._lock:
            namespace = self._base.setdefault(module_id, {})
            if not isinstance(namespace, dict):
                namespace = self._base[module_id] = {}
            merged = {**self.data.get(module_id, {}), **values}
            if spec:
                merged = schema.validate(spec, merged)
            # persist only the keys this call touched — validated and
            # clamped, but never the overlay's local values that happen
            # to sit in the merged view
            for key in values:
                namespace[key] = merged[key]
        self._refresh()
        self.save()
        return merged
