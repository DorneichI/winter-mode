"""Framework views: the home grid (FormView/InfoView arrive next step).

Views speak the same protocol as modules (render / on_tap), so they are
interchangeable stack entries.  Views never draw outside ctx.content and
never mutate config without going through ctx.config.
"""

from __future__ import annotations

from wintermode.context import Ctx
from wintermode.widgets import draw_button, draw_paginator, paginate

GRID_COLS = 4
GRID_ROWS = 2
CARD_PAGE_SIZE = GRID_COLS * GRID_ROWS
PAGE_MARGIN = 10
CARD_GAP = 10
PAGINATOR_H = 26


class HomeView:
    """The launcher: a paginated grid of cards, settings first."""

    title = "HOME"

    def __init__(self, registry=None, config=None) -> None:
        self.registry = registry
        self.config = config
        self.page = 0
        self._hitboxes: dict[tuple, object] = {}
        self._paginator: dict[str, tuple | None] = {"prev": None, "next": None}

    # --- card list ---------------------------------------------------------

    def _cards(self) -> list[tuple[str, object]]:
        """(label, target) pairs; target None for the static settings card."""
        cards: list[tuple[str, object]] = []
        modules = self.registry.home_order() if self.registry else []
        if not any(getattr(m, "id", None) == "settings" for m in modules):
            # static placeholder until the settings module exists
            cards.append(("SETTINGS", None))
        for module in modules:
            cards.append((module.title, module))
        return cards

    # --- layout ------------------------------------------------------------

    def _grid_rects(self, ctx: Ctx) -> list[tuple]:
        x0, y0, x1, y1 = ctx.content
        inner_w = x1 - x0 - 2 * PAGE_MARGIN
        inner_h = y1 - y0 - 2 * PAGE_MARGIN - PAGINATOR_H
        card_w = (inner_w - (GRID_COLS - 1) * CARD_GAP) // GRID_COLS
        card_h = (inner_h - (GRID_ROWS - 1) * CARD_GAP) // GRID_ROWS
        rects = []
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                cx0 = x0 + PAGE_MARGIN + col * (card_w + CARD_GAP)
                cy0 = y0 + PAGE_MARGIN + row * (card_h + CARD_GAP)
                rects.append((cx0, cy0, cx0 + card_w, cy0 + card_h))
        return rects

    # --- protocol ----------------------------------------------------------

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        cards = self._cards()
        pages, page_cards = paginate(cards, self.page, CARD_PAGE_SIZE)
        self.page = min(self.page, max(pages - 1, 0))

        rects = self._grid_rects(ctx)
        self._hitboxes = {}
        for rect, (label, target) in zip(rects, page_cards, strict=False):
            draw_button(draw, rect, label, ctx.fonts, ctx.theme)
            self._hitboxes[rect] = target

        x0, y0, x1, y1 = ctx.content
        self._paginator = draw_paginator(
            draw, (x0, y1 - PAGINATOR_H, x1, y1), self.page, pages,
            ctx.fonts, ctx.theme,
        )
        return True

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        for rect, target in self._hitboxes.items():
            x0, y0, x1, y1 = rect
            if x0 <= x < x1 and y0 <= y < y1:
                if target is not None:
                    ctx.nav.push(target)
                return True  # the static settings card is a no-op for now
        for action, rect in self._paginator.items():
            if rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                self.page += 1 if action == "next" else -1
                return True
        return False
