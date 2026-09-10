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

# "no value at all" — distinct from None, which is a value the caller
# may legitimately supply and which must be reported when rejected
ABSENT = object()


def _coerce(spec: dict, value: Any = ABSENT, strict: bool = False) -> Any:
    """Coerce `value` to `spec`'s type; ABSENT means "use the default"."""
    kind = spec.get("type")
    default = spec.get("default")
    if value is ABSENT:  # absent key: the default is not a rejection
        return default
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
            if value in spec.get("options", []):
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
        log.warning("config: unknown schema type %r for spec %r", kind, spec)
        raise ValueError(value)
    except (ValueError, TypeError, KeyError):
        if strict:
            raise
        log.warning(
            "config: %r rejected for %r (%s), using default %r",
            value, spec, kind, default,
        )
        return default


def coerce_bool(value: Any, default: bool = True) -> bool:
    """Coerce one standalone value to bool, the same way a spec would.

    For keys the config layer heals itself, where there is no per-key
    spec — `bool("false")` is True, which is not what a hand-edit means.
    """
    return _coerce({"type": "bool", "default": default}, value)


def validate_strict(schema: dict, values: dict) -> dict:
    """Like validate(), but rejects bad values instead of defaulting.

    Used by web PUT endpoints so a bogus body is a 400 and the config
    file stays untouched.
    """
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key not in schema:
            raise ValueError(f"unknown key {key!r}")
        out[key] = _coerce(schema[key], value, strict=True)
    return out


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
        out[key] = _coerce(spec, values.get(key, ABSENT))
    return out


# --- form-state transitions, shared by the touch form ---------------------
#
# Every one of these is None-tolerant: a spec with no `default` stores
# None, and a stepper tapped on such a field must not take the app down.


def toggle_bool(_spec: dict, value: Any) -> bool:
    return not bool(value)


def cycle_choice(spec: dict, value: Any) -> Any:
    options = spec.get("options") or []
    if not options:  # malformed spec: nothing to cycle to
        return value
    try:
        index = options.index(value)
    except ValueError:
        return options[0]
    return options[(index + 1) % len(options)]


def step_int(spec: dict, value: Any, delta: int) -> int:
    if value is None:
        value = spec.get("default", spec.get("min", 0))
    number = int(value) + delta
    return max(spec.get("min", number), min(spec.get("max", number), number))


def step_time(value: Any, part: str, delta: int, fallback: str = "00:00") -> str:
    """Bump the hour or minute of an "HH:MM" value (minutes step by 5)."""
    text = value if isinstance(value, str) else fallback
    if not TIME_RE.match(text):
        text = fallback
    hour, minute = (int(part_) for part_ in text.split(":"))
    if part == "hour":
        hour = (hour + delta) % 24
    else:
        minute = (minute + delta * 5) % 60
    return f"{hour:02d}:{minute:02d}"
