"""The dummy module: a demo of every contract surface.

Tap anywhere to bump the count (a touch write to config.json), the
count shows in the bar (status publishing), and the web UI gets a
"Reset" action button.  Its config schema demos the DSL types — the
settings form and the web form are generated from it.
"""

from __future__ import annotations

from wintermode.context import BarItem, Ctx
from wintermode.fonts import SIZE_CLOCK, SIZE_FORM
from wintermode.widgets import truncate

SIZE_HINT = SIZE_FORM  # the dim line under the big count

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
        ctx.fonts.draw_text(
            draw,
            ((x1 + x0 - width) / 2,
             ctx.fonts.center_y(count, "regular", SIZE_CLOCK, y0, y1 - 120)),
            count, "regular", SIZE_CLOCK, ctx.theme.fg,
        )
        # the greeting is user text of up to 64 chars: clamp it to the
        # panel instead of centring a 1400px line off both edges
        hint = truncate(ctx.fonts, f'greeting: "{data["greeting"]}"'
                        "   [tap anywhere to bump]", x1 - x0 - 24,
                        size=SIZE_HINT)
        width = ctx.fonts.textwidth(hint, "regular", SIZE_HINT)
        ctx.fonts.draw_text(
            draw,
            ((x1 + x0 - width) / 2,
             ctx.fonts.center_y(hint, "regular", SIZE_HINT, y1 - 96, y1 - 60)),
            hint, "regular", SIZE_HINT, ctx.theme.dim,
        )
        return True

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        count = ctx.config.data["dummy"]["count"] + 1
        # through the schema: past max the count pins at 99 here, instead
        # of being clamped behind our back by the next boot
        ctx.config.update_module("dummy", {"count": count}, spec=SCHEMA)
        return True

    def status_items(self, ctx: Ctx) -> list[BarItem]:
        return [BarItem(f"count {ctx.config.data['dummy']['count']}")]

    def on_action(self, action_id: str, ctx: Ctx) -> None:
        if action_id == "reset":
            ctx.config.update_module("dummy", {"count": 0}, spec=SCHEMA)


MODULE = Dummy()
