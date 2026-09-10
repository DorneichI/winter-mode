"""The clock module: a big time readout, plus the date in the bar.

Interval 1: the app re-invokes render() every second, but render
returns False when the displayed text hasn't changed, so a no-op second
costs one string comparison and no blit.
"""

from __future__ import annotations

import time

from wintermode.context import BarItem, Ctx
from wintermode.fonts import SIZE_CLOCK

SCHEMA = {
    "format24": {"type": "bool", "title": "24-hour", "default": True},
    "show_seconds": {"type": "bool", "title": "Show seconds", "default": False},
}


class Clock:
    id = "clock"
    title = "CLOCK"
    interval = 1
    config_schema = SCHEMA
    actions: list = []

    def __init__(self) -> None:
        self._last_text: str | None = None

    def _time_text(self, ctx: Ctx) -> str:
        fmt24 = ctx.config.data["clock"]["format24"]
        seconds = ctx.config.data["clock"]["show_seconds"]
        fmt = "%H:%M:%S" if seconds else "%H:%M"
        if not fmt24:
            # %I alone is a 12-hour clock with no way to tell 01:30 from
            # 13:30 — the meridiem is not optional
            fmt = fmt.replace("%H", "%I") + " %p"
        return time.strftime(fmt, time.localtime(ctx.wall))

    def render(self, draw, ctx: Ctx) -> bool:
        # always draws (forced re-renders must repaint after a theme
        # change); returns False when nothing changed so the interval
        # path can skip the blit
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        text = self._time_text(ctx)
        changed = text != self._last_text
        self._last_text = text
        x0, y0, x1, y1 = ctx.content
        width = ctx.fonts.textwidth(text, "regular", SIZE_CLOCK)
        ctx.fonts.draw_text(
            draw, ((x1 + x0 - width) / 2, (y1 + y0 - 44) / 2), text,
            "regular", SIZE_CLOCK, ctx.theme.fg,
        )
        date = time.strftime("%A %d.%m.%Y", time.localtime(ctx.wall))
        width = ctx.fonts.textwidth(date, "regular", 26)
        ctx.fonts.draw_text(draw, ((x1 + x0 - width) / 2, y1 - 90), date,
                            "regular", 26, ctx.theme.dim)
        return changed

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        return False

    def status_items(self, ctx: Ctx) -> list[BarItem]:
        return [BarItem(time.strftime("%d.%m.%Y", time.localtime(ctx.wall)))]

    def on_action(self, action_id: str, ctx: Ctx) -> None:
        pass


MODULE = Clock()
