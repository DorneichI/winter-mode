"""Framework views: the home grid and friends.

Step 2 placeholder — HomeView is a plain title for now; the card grid
lands in the next step.  Views speak the same protocol as modules
(render / on_tap), so they are interchangeable stack entries.
"""

from __future__ import annotations

from wintermode.context import Ctx


class HomeView:
    title = "HOME"

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        x0, y0 = ctx.content[0] + 8, ctx.content[1] + 8
        draw.text(
            (x0, y0), "HOME", font=ctx.fonts.get("regular", 18),
            fill=ctx.theme.dim,
        )
        return True

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        return False  # the grid arrives in the next step
