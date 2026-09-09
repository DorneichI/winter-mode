"""The config schema DSL — four flat types, two generated UIs.

One validator serves three callers: config load, the touch FormView
writes, and the web PUT endpoints.  Invalid values are coerced or
replaced by their default and logged — a hand-edited config.json never
crashes the app.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

TYPES = ("bool", "choice", "int", "text", "time")

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _coerce(spec: dict, value: Any) -> Any:
    kind = spec.get("type")
    default = spec.get("default")
    try:
        if kind == "bool":
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("true", "1", "yes", "on"):
                    return True
                if v in ("false", "0", "no", "off", ""):
                    return False
                raise ValueError(value)
            if isinstance(value, (bool, int)):
                return bool(value)
            raise ValueError(value)
        if kind == "choice":
            if value in spec["options"]:
                return value
            raise ValueError(value)
        if kind == "int":
            number = int(value)
            number = max(spec.get("min", number), min(spec.get("max", number), number))
            return number
        if kind == "text":
            if not isinstance(value, str):
                raise ValueError(value)
            return value[: spec.get("maxlength", len(value))]
        if kind == "time":
            if isinstance(value, str) and TIME_RE.match(value):
                return value
            raise ValueError(value)
    except (ValueError, TypeError, KeyError):
        log.warning(
            "config: %r rejected for %r (%s), using default %r",
            value, spec, kind, default,
        )
        return default
    log.warning("config: unknown schema type %r for spec %r", kind, spec)
    return default


def visible(spec: dict, values: dict) -> bool:
    """Honor a declarative `visible_if` condition.

    A spec may declare `"visible_if": {"field": "theme", "equals": "auto"}`
    — the field is then only rendered/editable when that other field
    holds that value.  One mechanism serves the touch form, the web
    form, and any future consumer; the value itself stays in config.
    """
    condition = spec.get("visible_if")
    if not condition:
        return True
    return values.get(condition["field"]) == condition["equals"]


def validate(schema: dict, values: dict | None) -> dict:
    """Coerce/validate `values` against `schema`.  Never raises.

    Missing keys are filled with defaults, unknown keys are dropped.
    A key present in `values` but absent from the schema is kept only
    if the schema is empty for that namespace — otherwise dropped.
    """
    if not isinstance(values, dict):
        values = {}
    out: dict[str, Any] = {}
    for key, spec in schema.items():
        out[key] = _coerce(spec, values.get(key))
    return out


# --- form-state transitions, shared by the touch form ---------------------


def toggle_bool(_spec: dict, value: Any) -> bool:
    return not bool(value)


def cycle_choice(spec: dict, value: Any) -> Any:
    options = spec["options"]
    try:
        index = options.index(value)
    except ValueError:
        return options[0]
    return options[(index + 1) % len(options)]


def step_int(spec: dict, value: Any, delta: int) -> int:
    number = int(value) + delta
    return max(spec.get("min", number), min(spec.get("max", number), number))


def step_time(value: Any, part: str, delta: int) -> str:
    """Bump the hour or minute of an "HH:MM" value (minutes step by 5)."""
    hour, minute = (int(part_) for part_ in value.split(":"))
    if part == "hour":
        hour = (hour + delta) % 24
    else:
        minute = (minute + delta * 5) % 60
    return f"{hour:02d}:{minute:02d}"
