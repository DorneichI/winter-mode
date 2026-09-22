"""The settings hub: a card grid into every configurable thing.

Device-level cards (DISPLAY, STATUS BAR, SYSTEM) plus one card per
module with a config_schema — all auto-generated FormViews or read-only
InfoViews.  Tap a card, edit, [‹ BACK] out.

The device cards are built from `wintermode.device`, the same
descriptors the web API serves, so the two surfaces always show the same
groups with the same schemas.
"""

from __future__ import annotations

import socket
import time

from wintermode import device
from wintermode.context import Ctx
from wintermode.net import ipv4 as _ipv4
from wintermode.net import web_url
from wintermode.version import read_deployed_version
from wintermode.views import CardGrid, FormView, InfoView

START = time.time()


def _uptime() -> str:
    seconds = int(time.time() - START)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


class Settings(CardGrid):
    id = "settings"
    title = "SETTINGS"
    interval = 0
    config_schema = None
    status_bar = False  # nothing of the hub's belongs in the status bar
    actions: list = []

    def __init__(self) -> None:
        super().__init__()
        # two namespaces: a module whose id matches a device page name
        # must still get its own form, not the device view
        self._device_views: dict[str, object] = {}
        self._module_views: dict[str, object] = {}
        self._web_port: int | None = None
        self._system_config_path = None  # captured when the view is built

    # --- hub cards ----------------------------------------------------------

    def cards(self, ctx: Ctx) -> list[tuple[str, object]]:
        self._web_port = ctx.web_port  # refreshed every render
        cards: list[tuple[str, object]] = [
            (group.title, self._device_view(group, ctx))
            for group in device.groups(ctx.config, ctx.registry)
        ]
        cards.append(("SYSTEM", self._system_view(ctx)))
        for module in ctx.registry.home_order():
            if module.id != self.id and module.config_schema:
                cards.append((module.title, self._module_view(module, ctx)))
        return cards

    def _device_view(self, group, ctx: Ctx) -> FormView:
        """One form per device group, built from its shared descriptor."""
        if group.id not in self._device_views:
            self._device_views[group.id] = FormView(
                group.title, group.schema, group.read,
                # every write goes back through the group's validator,
                # so the panel and the web API save identical values
                lambda key, value, g=group: g.apply({key: value}),
            )
        return self._device_views[group.id]

    def _system_view(self, ctx: Ctx) -> InfoView:
        if "system" not in self._device_views:
            # the version stamp lives next to the config: capture where
            # the config IS at build time (the view is cached)
            self._system_config_path = ctx.config.path
            self._device_views["system"] = InfoView("SYSTEM", [
                ("HOST", lambda: socket.gethostname()),
                ("VERSION", lambda: read_deployed_version(
                    self._system_config_path)),
                ("UPTIME", _uptime),
                ("IP", _ipv4),
                ("WEB", lambda: web_url(self._web_port)),
            ])
        return self._device_views["system"]

    def _module_view(self, module, ctx: Ctx) -> FormView:
        if module.id not in self._module_views:
            config = ctx.config
            self._module_views[module.id] = FormView(
                module.title, module.config_schema,
                lambda m=module: {
                    key: config.namespace(m.id).get(key)
                    for key in m.config_schema
                },
                # the spec is what routes a local (secret) field to the
                # overlay and clamps the rest — never write without it
                lambda key, value, m=module: config.update_module(
                    m.id, {key: value}, m.config_schema),
            )
        return self._module_views[module.id]

    # --- protocol -----------------------------------------------------------

    def on_card(self, target: object, ctx: Ctx) -> None:
        ctx.nav.push(target)

    def status_items(self, ctx: Ctx) -> list:
        return []

    def on_action(self, action_id: str, ctx: Ctx) -> None:
        pass


MODULE = Settings()
