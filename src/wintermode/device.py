"""The device-level config groups, defined exactly once.

DISPLAY and STATUS BAR are the settings that belong to the device rather
than to any one module.  Both surfaces — the touch SETTINGS page and the
web API — build their forms from the descriptors here, so a group can
never exist on one surface and not the other, and a schema can never
drift between them (the two used to disagree about whether the settings
module itself gets a status-bar toggle).

A group is a plain record: a schema (the same DSL modules use), a
`values()` that reads current config, and an `apply()` that validates a
patch and writes it.  Add a group once and it appears in both UIs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from wintermode import schema
from wintermode.config import DISPLAY_PAGE_SCHEMA, THEME_SCHEMA, UPDATES_SCHEMA

# the status-bar rotation interval lives in this key, not in the
# per-module statusbar map (it is a number, not a toggle)
ROTATE_KEY = "rotate_seconds"
ROTATE_SPEC = {"type": "int", "title": "Rotate every (s)",
               "min": 0, "max": 3600, "default": 10}


@dataclass(frozen=True)
class DeviceGroup:
    """One settings page: schema + live values + a validated write path."""

    id: str
    title: str
    schema: dict
    values: Callable[[], dict]
    apply: Callable[[dict], None]

    def read(self) -> dict:
        return {key: self.values().get(key) for key in self.schema}


def statusbar_ids(registry) -> list[str]:
    """Modules that can publish status items, in home order.

    A module opts out by declaring `status_bar = False` (the settings hub
    does: it has nothing to say in the bar), so the rule is a property of
    the module rather than a hardcoded id in each surface.
    """
    if registry is None:  # a bare Ctx (tests, tools) has no modules
        return []
    return [module.id for module in registry.home_order()
            if getattr(module, "status_bar", True)]


def statusbar_schema(registry) -> dict:
    out: dict = {
        mid: {"type": "bool", "title": registry.get(mid).title + " bar",
              "default": True}
        for mid in statusbar_ids(registry)
    }
    out[ROTATE_KEY] = dict(ROTATE_SPEC)
    return out


def display_group(config) -> DeviceGroup:
    def values() -> dict:
        return {"theme": config.data["theme"], **config.data.get("display", {})}

    def apply(patch: dict) -> None:
        clean = schema.validate_strict(DISPLAY_PAGE_SCHEMA, patch)
        config.update({
            "theme": clean.get("theme", config.data["theme"]),
            "display": {key: value for key, value in clean.items()
                        if key != "theme"},
        })

    return DeviceGroup("display", "DISPLAY", DISPLAY_PAGE_SCHEMA, values, apply)


def statusbar_group(config, registry) -> DeviceGroup:
    def values() -> dict:
        return {
            mid: config.data["statusbar"].get(mid, True)
            for mid in statusbar_ids(registry)
        } | {ROTATE_KEY: config.data.get("statusbar_rotate", 10)}

    def apply(patch: dict) -> None:
        clean = schema.validate_strict(statusbar_schema(registry), patch)
        rotate = clean.pop(ROTATE_KEY, config.data.get("statusbar_rotate", 10))
        config.update({"statusbar": clean, "statusbar_rotate": rotate})

    return DeviceGroup("statusbar", "STATUS BAR", statusbar_schema(registry),
                       values, apply)


def theme_group(config) -> DeviceGroup:
    """The theme alone — kept because the documented API exposes it.

    The UI merges the theme into DISPLAY; this group exists so
    `PUT /api/device/theme` (README) is not a 404.
    """
    def values() -> dict:
        return {"theme": config.data["theme"]}

    def apply(patch: dict) -> None:
        clean = schema.validate_strict(THEME_SCHEMA, patch)
        config.update(clean)

    return DeviceGroup("theme", "THEME", THEME_SCHEMA, values, apply)


def updates_group(config) -> DeviceGroup:
    """The auto-update toggle: reads/applies the root "updates" key.

    The boot updater reads config.json raw (it cannot import wintermode),
    so this group and UPDATES_SCHEMA are the only writer of the key —
    and "updates" is in config.RESERVED, so no module namespace can
    ever shadow it.
    """
    def values() -> dict:
        namespace = config.data.get("updates")
        if not isinstance(namespace, dict):
            namespace = {}
        return {"auto": bool(namespace.get("auto", True))}

    def apply(patch: dict) -> None:
        clean = schema.validate_strict(UPDATES_SCHEMA, patch)
        config.update({"updates": clean})  # deep-merge: extra keys survive

    return DeviceGroup("updates", "UPDATES", UPDATES_SCHEMA, values, apply)


def groups(config, registry) -> list[DeviceGroup]:
    """The device pages, in the order both UIs show them."""
    return [display_group(config), statusbar_group(config, registry),
            updates_group(config)]


def group_by_id(config, registry, group_id: str) -> DeviceGroup | None:
    """Look one up by id, including the theme alias group."""
    if group_id == "theme":
        return theme_group(config)
    for group in groups(config, registry):
        if group.id == group_id:
            return group
    return None
