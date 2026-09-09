"""Framework views: card grids, auto-generated forms, info rows.

Views speak the same protocol as modules (render / on_tap), so they are
interchangeable stack entries.  Views never draw outside ctx.content and
never mutate config without going through ctx.config.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wintermode.context import Ctx
from wintermode.fonts import SIZE_FORM, SIZE_PAGINATOR
from wintermode.schema import (
    cycle_choice,
    step_int,
    step_time,
    toggle_bool,
    visible,
)
from wintermode.widgets import (
    draw_button,
    draw_button_auto,
    draw_paginator,
    paginate,
    truncate,
)

GRID_COLS = 4
GRID_ROWS = 2
CARD_PAGE_SIZE = GRID_COLS * GRID_ROWS
PAGE_MARGIN = 10
CARD_GAP = 10
PAGINATOR_H = 26

ROW_H = 40
FORM_PAGE_MARGIN = 10


class CardGrid:
    """A paginated grid of bordered cards: tap a card, get a callback."""

    title = "HOME"

    def __init__(self) -> None:
        self.page = 0
        self._hitboxes: dict[tuple, object] = {}
        self._paginator: dict[str, tuple | None] = {"prev": None, "next": None}

    # --- subclass hooks ------------------------------------------------------

    def cards(self, ctx: Ctx) -> list[tuple[str, object]]:
        """(label, target) pairs; the grid pages over them."""
        raise NotImplementedError

    def on_card(self, target: object, ctx: Ctx) -> None:
        """A card was tapped; the default is to push its target."""

    # --- layout -------------------------------------------------------------

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

    # --- protocol -----------------------------------------------------------

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        cards = self.cards(ctx)
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
                self.on_card(target, ctx)
                return True
        for action, rect in self._paginator.items():
            if rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                self.page += 1 if action == "next" else -1
                return True
        return False


class HomeView(CardGrid):
    """The launcher: every enabled module gets a card, settings first."""

    title = "HOME"

    def __init__(self, registry=None, config=None) -> None:
        super().__init__()
        self.registry = registry
        self.config = config

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

    def cards(self, ctx: Ctx) -> list[tuple[str, object]]:
        return self._cards()

    def on_card(self, target: object, ctx: Ctx) -> None:
        if target is not None:
            ctx.nav.push(target)


class FormView:
    """An auto-generated settings page from a config_schema.

    One row per field: toggle, cycle, stepper — text fields are
    read-only here (they edit on the web).  Every write goes through
    set_value, which persists via ctx.config.
    """

    title = "SETTINGS"

    def __init__(
        self,
        title: str,
        schema: dict,
        get_values: Callable[[], dict],
        set_value: Callable[[str, Any], None],
    ) -> None:
        self.title = title
        self.schema = schema
        self.get_values = get_values
        self.set_value = set_value
        self.page = 0
        self._rows: list[tuple[tuple, str, str]] = []  # (rect, key, action)
        self._paginator: dict[str, tuple | None] = {"prev": None, "next": None}

    def _fields(self) -> list[tuple[str, dict]]:
        return list(self.schema.items())

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        values = self.get_values()
        # only fields whose visible_if condition holds are rendered
        fields = [(key, spec) for key, spec in self._fields()
                  if visible(spec, values)]
        pages, page_fields = paginate(fields, self.page, self._rows_per_page(ctx))
        self.page = min(self.page, max(pages - 1, 0))

        x0, y0, x1, y1 = ctx.content
        self._rows = []
        for i, (key, spec) in enumerate(page_fields):
            ry = y0 + FORM_PAGE_MARGIN + i * ROW_H
            self._render_field(draw, ctx, key, spec, values.get(key), x0, ry, x1)

        self._paginator = draw_paginator(
            draw, (x0, y1 - PAGINATOR_H, x1, y1), self.page, pages,
            ctx.fonts, ctx.theme, size=SIZE_PAGINATOR,
        )
        return True

    def _rows_per_page(self, ctx: Ctx) -> int:
        available = ctx.content[3] - ctx.content[1] - 2 * FORM_PAGE_MARGIN - PAGINATOR_H
        return max(1, available // ROW_H)

    def _stepper_width(self, fonts) -> int:
        """Both - and + buttons share this width — always equal."""
        return max(fonts.textwidth("+", "regular", SIZE_FORM),
                   fonts.textwidth("-", "regular", SIZE_FORM)) + 24

    def _render_field(self, draw, ctx: Ctx, key: str, spec: dict, value: Any,
                      x0: int, y0: int, x1: int) -> None:
        theme = ctx.theme
        fonts = ctx.fonts
        label = truncate(fonts, spec.get("title", key).upper(), 340,
                         size=SIZE_FORM)
        fonts.draw_text(draw, (x0 + 12, y0 + (ROW_H - 26) // 2), label,
                        "regular", SIZE_FORM, theme.dim)

        if spec["type"] == "bool":
            # plain box; on = a white X, no inverse video
            rect = draw_button_auto(
                draw, x1 - 12, y0 + 4, ROW_H - 8,
                "X" if value else " ", fonts, theme, size=SIZE_FORM,
                min_width=44,
            )
            self._rows.append((rect, key, "toggle"))
        elif spec["type"] == "choice":
            rect = draw_button_auto(
                draw, x1 - 12, y0 + 4, ROW_H - 8,
                f"{value} [next ›]", fonts, theme, size=SIZE_FORM,
            )
            self._rows.append((rect, key, "cycle"))
        elif spec["type"] == "int":
            step_w = self._stepper_width(fonts)
            value_w = fonts.textwidth(str(value), "regular", SIZE_FORM)
            plus = (x1 - 12 - step_w, y0 + 4, x1 - 12, y0 + ROW_H - 4)
            minus = (plus[0] - value_w - 24 - step_w, y0 + 4,
                     plus[0] - value_w - 24, y0 + ROW_H - 4)
            draw_button(draw, minus, "-", fonts, theme, size=SIZE_FORM)
            draw_button(draw, plus, "+", fonts, theme, size=SIZE_FORM)
            fonts.draw_text(
                draw, (plus[0] - 12 - value_w, y0 + (ROW_H - 26) // 2),
                str(value), "regular", SIZE_FORM, theme.fg,
            )
            self._rows.append((minus, key, "minus"))
            self._rows.append((plus, key, "plus"))
        elif spec["type"] == "time":
            self._render_time_field(draw, ctx, key, value, x0, y0, x1)
        else:  # text: read-only on the device, editable on the web
            shown = truncate(fonts, str(value), 300, size=SIZE_FORM)
            width = fonts.textwidth(shown, "regular", SIZE_FORM)
            fonts.draw_text(draw, (x1 - 12 - width, y0 + (ROW_H - 26) // 2),
                            shown, "regular", SIZE_FORM, theme.dim)
            fonts.draw_text(draw, (x1 - 330, y0 + (ROW_H - 26) // 2),
                            "(web)", "regular", SIZE_FORM, theme.dim)

    def _render_time_field(self, draw, ctx: Ctx, key: str, value: Any,
                           x0: int, y0: int, x1: int) -> None:
        fonts = ctx.fonts
        theme = ctx.theme
        step_w = self._stepper_width(fonts)
        text_w = fonts.textwidth(str(value), "regular", SIZE_FORM)
        pair = 2 * step_w + 8
        total = text_w + 14 + pair + 14 + pair
        left = x1 - 12 - total
        ty = y0 + (ROW_H - 26) // 2
        fonts.draw_text(draw, (left, ty), str(value), "regular", SIZE_FORM,
                        theme.fg)
        h_minus = (left + text_w + 14, y0 + 4, left + text_w + 14 + step_w,
                   y0 + ROW_H - 4)
        h_plus = (h_minus[2] + 8, y0 + 4, h_minus[2] + 8 + step_w,
                  y0 + ROW_H - 4)
        m_minus = (h_plus[2] + 14, y0 + 4, h_plus[2] + 14 + step_w,
                   y0 + ROW_H - 4)
        m_plus = (m_minus[2] + 8, y0 + 4, m_minus[2] + 8 + step_w,
                  y0 + ROW_H - 4)
        for rect, label in ((h_minus, "-"), (h_plus, "+"),
                            (m_minus, "-"), (m_plus, "+")):
            draw_button(draw, rect, label, fonts, theme, size=SIZE_FORM)
        self._rows.append((h_minus, key, "hour-"))
        self._rows.append((h_plus, key, "hour+"))
        self._rows.append((m_minus, key, "minute-"))
        self._rows.append((m_plus, key, "minute+"))

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        for (rx0, ry0, rx1, ry1), key, action in self._rows:
            if rx0 <= x < rx1 and ry0 <= y < ry1:
                value = self.get_values().get(key)
                spec = self.schema[key]
                if action == "toggle":
                    new = toggle_bool(spec, value)
                elif action == "cycle":
                    new = cycle_choice(spec, value)
                elif action in ("hour-", "hour+", "minute-", "minute+"):
                    part = "hour" if action.startswith("hour") else "minute"
                    new = step_time(value, part, 1 if action.endswith("+") else -1)
                else:
                    new = step_int(spec, value, 1 if action == "plus" else -1)
                    if new == value:  # already at the bound: nothing to save
                        return True
                self.set_value(key, new)
                return True
        for action, rect in self._paginator.items():
            if rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                self.page += 1 if action == "next" else -1
                return True
        return False


class InfoView:
    """Read-only rows: dim labels left, live values right."""

    def __init__(self, title: str, rows: list[tuple[str, Callable[[], str]]]) -> None:
        self.title = title
        self.rows = rows

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        x0, y0, x1, _y1 = ctx.content
        for i, (label, value_fn) in enumerate(self.rows):
            ry = y0 + FORM_PAGE_MARGIN + i * ROW_H
            ctx.fonts.draw_text(draw, (x0 + 12, ry + (ROW_H - 26) // 2),
                                label, "regular", SIZE_FORM, ctx.theme.dim)
            value = value_fn()
            width = ctx.fonts.textwidth(value, "regular", SIZE_FORM)
            ctx.fonts.draw_text(draw, (x1 - 12 - width, ry + (ROW_H - 26) // 2),
                                value, "regular", SIZE_FORM, ctx.theme.fg)
        return True

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        return False
