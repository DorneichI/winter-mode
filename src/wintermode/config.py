"""config.json: defaults-merged, atomically written, live-reloadable.

Writes go through a temp file + os.replace under a lock, so a crash
mid-write can never truncate the config.  Every save bumps `generation`;
the main loop watches it to reload live.  Reserved top-level keys are
validated here; per-module namespaces are validated by the registry
against each module's config_schema.
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
    "idle_seconds": DISPLAY_SCHEMA["idle_seconds"],
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
    return {
        key: bool(enabled) for key, enabled in value.items() if isinstance(key, str)
    }


class Config:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.generation = 0
        self.data: dict[str, Any] = self._load()
        if not self.path.exists():
            log.info("config: no %s, writing defaults", self.path)
            self.save()

    # --- loading -----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        data = deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text())
            except (OSError, ValueError):
                log.warning("config: unreadable %s, using defaults", self.path)
                raw = {}
            if isinstance(raw, dict):
                _deep_update(data, raw)
        data.update(schema.validate(THEME_SCHEMA, data))
        data.update(schema.validate(ROTATE_SCHEMA, data))
        data["display"] = schema.validate(DISPLAY_SCHEMA, data.get("display"))
        data["modules"] = _coerce_modules(data.get("modules"))
        data["statusbar"] = _coerce_statusbar(data.get("statusbar"))
        return data

    # --- writing -----------------------------------------------------------

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                tmp.write_text(json.dumps(self.data, indent=2) + "\n")
                tmp.replace(self.path)
            except OSError:
                log.warning("config: could not write %s (read-only?)", self.path)
                return
            self.generation += 1

    # --- mutation ----------------------------------------------------------

    def update(self, mapping: dict[str, Any], save: bool = True) -> None:
        """Deep-merge top-level namespaces (e.g. {"theme": "night"})."""
        with self._lock:
            _deep_update(self.data, mapping)
        if save:
            self.save()

    def update_module(self, module_id: str, values: dict, save: bool = True) -> None:
        with self._lock:
            _deep_update(self.data.setdefault(module_id, {}), values)
        if save:
            self.save()
