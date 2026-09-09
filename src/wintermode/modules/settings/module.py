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
from wintermode.config import DISPLAY_SCHEMA, THEME_SCHEMA
from wintermode.context import Ctx
from wintermode.views import CardGrid, FormView, InfoView

# the theme page: the theme choice plus the auto-schedule window —
# the times only appear while theme is "auto" (declarative visible_if)
THEME_PAGE_SCHEMA = {
    **THEME_SCHEMA,
    "light_from": {"type": "time", "title": "Light from", "default": "07:00",
                   "visible_if": {"field": "theme", "equals": "auto"}},
    "light_to": {"type": "time", "title": "Light to", "default": "19:00",
                 "visible_if": {"field": "theme", "equals": "auto"}},
}

START = time.time()


def _ipv4() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "unknown"


def _web_url() -> str:
    return f"http://{_ipv4()}:8080"  # port: the web server (step 6)


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
            ("THEME", self._views["theme"]),
            ("STATUS BAR", self._views["statusbar"]),
            ("DISPLAY", self._views["display"]),
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
            "theme": FormView(
                "THEME", THEME_PAGE_SCHEMA,
                lambda: {
                    key: config.data["theme"] if key == "theme"
                    else config.data["display"].get(key)
                    for key in THEME_PAGE_SCHEMA
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
            "display": FormView(
                "DISPLAY", DISPLAY_SCHEMA,
                lambda: {key: config.data["display"].get(key)
                         for key in DISPLAY_SCHEMA},
                lambda key, value: config.update({"display": {key: value}}),
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
