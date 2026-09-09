"""The settings hub: a card grid into every configurable thing.

Device-level cards (theme + auto schedule, status bar + rotation,
display, system info) plus one card per module with a config_schema —
all auto-generated FormViews or read-only InfoViews.  Tap a card,
edit, [‹ BACK] out.
"""

from __future__ import annotations

import socket
import time

from wintermode import __version__
from wintermode.config import DISPLAY_PAGE_SCHEMA
from wintermode.context import Ctx
from wintermode.net import ipv4 as _ipv4
from wintermode.views import CardGrid, FormView, InfoView

START = time.time()


def _web_url() -> str:
    return f"http://{_ipv4()}:8080"


def _uptime() -> str:
    seconds = int(time.time() - START)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


class Settings(CardGrid):
    id = "settings"
    title = "SETTINGS"
    interval = 0
    config_schema = None
    actions: list = []

    def __init__(self) -> None:
        super().__init__()
        self._views: dict[str, object] = {}

    # --- hub cards ----------------------------------------------------------

    def cards(self, ctx: Ctx) -> list[tuple[str, object]]:
        if not self._views:
            self._build_views(ctx)
        cards: list[tuple[str, object]] = [
            ("DISPLAY", self._views["display"]),
            ("STATUS BAR", self._views["statusbar"]),
            ("SYSTEM", self._views["system"]),
        ]
        for module in ctx.registry.home_order():
            if module.id != self.id and module.config_schema:
                cards.append((module.title, self._module_view(module, ctx)))
        return cards

    def _build_views(self, ctx: Ctx) -> None:
        config = ctx.config  # one Config for the process lifetime

        def statusbar_ids():
            return [m.id for m in ctx.registry.home_order() if m.id != self.id]

        def statusbar_schema():
            schema = {
                mid: {"type": "bool",
                      "title": ctx.registry.get(mid).title + " bar",
                      "default": True}
                for mid in statusbar_ids()
            }
            schema["rotate_seconds"] = {
                "type": "int", "title": "Rotate every (s)",
                "min": 0, "max": 3600, "default": 10,
            }
            return schema

        self._views = {
            "display": FormView(
                "DISPLAY", DISPLAY_PAGE_SCHEMA,
                lambda: {
                    key: config.data["theme"] if key == "theme"
                    else config.data["display"].get(key)
                    for key in DISPLAY_PAGE_SCHEMA
                },
                lambda key, value: config.update(
                    {"theme": value} if key == "theme"
                    else {"display": {key: value}}),
            ),
            "statusbar": FormView(
                "STATUS BAR", statusbar_schema(),
                lambda: {
                    key: config.data["statusbar_rotate"] if key == "rotate_seconds"
                    else config.data["statusbar"].get(key, True)
                    for key in statusbar_schema()
                },
                lambda key, value: config.update(
                    {"statusbar_rotate": value} if key == "rotate_seconds"
                    else {"statusbar": {key: value}}),
            ),
            "system": InfoView("SYSTEM", [
                ("HOST", lambda: socket.gethostname()),
                ("VERSION", lambda: __version__),
                ("UPTIME", _uptime),
                ("IP", _ipv4),
                ("WEB", _web_url),
            ]),
        }

    def _module_view(self, module, ctx: Ctx) -> FormView:
        if module.id not in self._views:
            config = ctx.config
            self._views[module.id] = FormView(
                module.title, module.config_schema,
                lambda m=module: {
                    key: config.data.get(m.id, {}).get(key)
                    for key in m.config_schema
                },
                lambda key, value, m=module: config.update_module(
                    m.id, {key: value}),
            )
        return self._views[module.id]

    # --- protocol -----------------------------------------------------------

    def on_card(self, target: object, ctx: Ctx) -> None:
        ctx.nav.push(target)

    def status_items(self, ctx: Ctx) -> list:
        return []

    def on_action(self, action_id: str, ctx: Ctx) -> None:
        pass


MODULE = Settings()
