"""The config schema DSL — four flat types, two generated UIs.

One validator serves three callers: config load, the touch FormView
writes, and the web PUT endpoints.  Invalid values are coerced or
replaced by their default and logged — a hand-edited config.json never
crashes the app.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

TYPES = ("bool", "choice", "int", "text")


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
    except (ValueError, TypeError, KeyError):
        log.warning(
            "config: %r rejected for %r (%s), using default %r",
            value, spec, kind, default,
        )
        return default
    log.warning("config: unknown schema type %r for spec %r", kind, spec)
    return default


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
