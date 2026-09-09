"""The dummy module: a demo of every contract surface.

Tap anywhere to bump the count (a touch write to config.json), the
count shows in the bar (status publishing), and the web UI gets a
"Reset" action button.  Its config schema demos all four DSL types —
the settings form and the web form are generated from it.
"""

from __future__ import annotations

from wintermode.context import BarItem, Ctx
from wintermode.fonts import SIZE_CLOCK

SCHEMA = {
    "flash": {"type": "bool", "title": "Flash", "default": False},
    "mode": {"type": "choice", "title": "Mode",
             "options": ["count", "wave", "off"], "default": "count"},
    "count": {"type": "int", "title": "Count", "min": 0, "max": 99,
              "default": 0},
    "greeting": {"type": "text", "title": "Greeting", "maxlength": 64,
                 "default": "hello"},
}


class Dummy:
    id = "dummy"
    title = "DUMMY"
    interval = 0
    config_schema = SCHEMA
    actions = [{"id": "reset", "title": "Reset"}]

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        data = ctx.config.data["dummy"]
        count = str(data["count"])
        x0, y0, x1, y1 = ctx.content
        width = ctx.fonts.textwidth(count, "regular", SIZE_CLOCK)
        ctx.fonts.draw_text(draw, ((x1 + x0 - width) / 2, (y1 + y0) / 2 - 60),
                            count, "regular", SIZE_CLOCK, ctx.theme.fg)
        hint = f'greeting: "{data["greeting"]}"   [tap anywhere to bump]'
        width = ctx.fonts.textwidth(hint, "regular", 26)
        ctx.fonts.draw_text(draw, ((x1 + x0 - width) / 2, y1 - 90), hint,
                            "regular", 26, ctx.theme.dim)
        return True

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        count = ctx.config.data["dummy"]["count"] + 1
        ctx.config.update_module("dummy", {"count": count})
        return True

    def status_items(self, ctx: Ctx) -> list[BarItem]:
        return [BarItem(f"count {ctx.config.data['dummy']['count']}")]

    def on_action(self, action_id: str, ctx: Ctx) -> None:
        if action_id == "reset":
            ctx.config.update_module("dummy", {"count": 0})


MODULE = Dummy()
