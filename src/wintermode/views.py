"""Framework views: card grids, lists, pickers, auto-generated forms.

Views speak the same protocol as modules (render / on_tap), so they are
interchangeable stack entries.  Views never draw outside ctx.content and
never mutate config without going through ctx.config.

Everything here is a reusable primitive — a module can build a list, a
picker or a confirm dialog without writing layout code:

    ctx.nav.push(ListView("CITIES", rows_fn, on_change=save))
    ctx.nav.push(PickerView("THEME", ["dark", "light"], on_pick=set_theme))
    ctx.nav.push(ConfirmView("RESET", "clear all counters?", on_confirm=do_it))

FormView is nothing more than a ListView whose rows are derived from a
schema, so a schema field and a hand-built row can never drift apart.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
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
    draw_scroller,
    paginate,
    text_y,
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

# editable row kinds; "info" and "text" are read-only on the device
ROW_KINDS = ("info", "bool", "choice", "int", "time", "text")

# how a tapped row reports itself in view._rows: (rect, key, action)
TAP_ACTIONS = {
    "bool": ("toggle",),
    "choice": ("cycle",),
    "int": ("minus", "plus"),
    "time": ("hour-", "hour+", "minute-", "minute+"),
}


def _paged(items: list, page: int, page_size: int) -> tuple[int, int, list]:
    """(page count, clamped page, items on that page).

    The clamp happens BEFORE the slice: a collection that shrank under a
    stale page index would otherwise render an empty page for a frame
    and only heal on a re-render that may never come.
    """
    pages = paginate(items, 0, page_size)[0]
    page = min(max(page, 0), max(pages - 1, 0))
    _pages, page_items = paginate(items, page, page_size)
    return pages, page, page_items


class PagedMixin:
    """Shared page bookkeeping + prev/next/scroll hitbox handling."""

    def __init__(self) -> None:
        self.page = 0
        self._paginator: dict[str, tuple | None] = {"prev": None, "next": None}
        self._offset = 0
        self._scroller: dict[str, tuple | None] = {"up": None, "down": None}

    def _tap_paginator(self, x: int, y: int) -> bool:
        for action, rect in self._paginator.items():
            if rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                self.page += 1 if action == "next" else -1
                return True
        return False

    def _tap_scroller(self, x: int, y: int) -> bool:
        for action, rect in self._scroller.items():
            if rect and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                self._offset += 1 if action == "down" else -1
                return True
        return False


class CardGrid(PagedMixin):
    """A paginated grid of bordered cards: tap a card, get a callback."""

    title = "HOME"

    def __init__(self) -> None:
        super().__init__()
        self._hitboxes: dict[tuple, object] = {}

    # --- subclass hooks ------------------------------------------------------

    def cards(self, ctx: Ctx) -> list[tuple[str, object]]:
        """(label, target) pairs; the grid pages over them."""
        raise NotImplementedError

    def on_card(self, target: object, ctx: Ctx) -> None:
        """A card was tapped; the default is to push it on the nav stack.

        Push anything with the view protocol (render / on_tap) — a module,
        a FormView, a ListView, a PickerView.
        """
        if target is not None:
            ctx.nav.push(target)

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
        pages, self.page, page_cards = _paged(cards, self.page, CARD_PAGE_SIZE)

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
        return self._tap_paginator(x, y)


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


# --- reusable rows ---------------------------------------------------------


@dataclass
class Row:
    """One line of a ListView — and the unit a PickerView picks.

    `kind` decides the control drawn on the right: "info"/"text" are
    read-only, the rest are editable (bool -> toggle, choice -> cycle,
    int -> steppers, time -> hour/minute steppers).  `spec` is an
    optional schema dict supplying min/max/options/maxlength.
    """

    key: str
    label: str
    value: Any = None
    kind: str = "info"
    spec: dict = field(default_factory=dict)


class ListView(PagedMixin):
    """A paginated list of rows: dim label left, live control right.

    Subclass and override rows(), on_change() and on_select() — or push
    one straight onto the nav stack with callbacks, which is all
    PickerView is.  A tap that changes a value re-renders the *next*
    frame via the app loop, so on_change never draws.

    `scroll = True` swaps pagination for vertical scrolling: rows are
    drawn from a clamped offset and [▲] [▼] buttons appear automatically
    whenever the list overflows — grey and inert at the ends.
    """

    title = "LIST"
    interval = 0
    scroll = False
    on_change: Callable[[Row, Any, Ctx], None] | None = None
    on_select: Callable[[Row, Ctx], None] | None = None

    def __init__(
        self,
        title: str,
        rows: Callable[[Ctx], list[Row]] | list[Row],
        on_change: Callable[[Row, Any, Ctx], None] | None = None,
        on_select: Callable[[Row, Ctx], None] | None = None,
    ) -> None:
        super().__init__()
        self.title = title
        self._rows_fn = rows if callable(rows) else (lambda _ctx: rows)
        # never bind None over a subclass's own method — only an explicit
        # callback replaces the hook
        if on_change is not None:
            self.on_change = on_change
        if on_select is not None:
            self.on_select = on_select
        self._rows: list[tuple[tuple, str, str]] = []  # (rect, key, action)

    # --- subclass hooks ------------------------------------------------------

    def rows(self, ctx: Ctx) -> list[Row]:
        return self._rows_fn(ctx)

    def value_text(self, row: Row) -> str:
        """The control's label for a value-bearing row."""
        return "" if row.value is None else str(row.value)

    # --- protocol -----------------------------------------------------------

    def _rows_per_page(self, ctx: Ctx) -> int:
        available = (ctx.content[3] - ctx.content[1] - 2 * FORM_PAGE_MARGIN
                     - PAGINATOR_H - self._header_h(ctx))
        return max(1, available // ROW_H)

    def _scroll_visible(self, rows: list[Row], per_page: int) -> list[Row]:
        """The offset-clamped window over the rows, in scroll mode.

        The clamp happens BEFORE the slice — a collection that shrank
        under a stale offset would otherwise render past its end.
        """
        self._offset = min(max(self._offset, 0), max(len(rows) - per_page, 0))
        return rows[self._offset : self._offset + per_page]

    def _header_h(self, ctx: Ctx) -> int:
        """Rows start below this many pixels of optional header."""
        return 0

    def _draw_header(self, draw, ctx: Ctx) -> None:
        """A view's own heading/message; the default draws nothing."""

    def render(self, draw, ctx: Ctx) -> bool:
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        x0, y0, x1, y1 = ctx.content
        self._draw_header(draw, ctx)
        y0 += self._header_h(ctx)
        rows = self.rows(ctx)
        per_page = self._rows_per_page(ctx)
        strip = (x0, y1 - PAGINATOR_H, x1, y1)
        if self.scroll:
            visible_rows = self._scroll_visible(rows, per_page)
            self._scroller = draw_scroller(
                draw, strip, self._offset, len(visible_rows), len(rows),
                ctx.fonts, ctx.theme, size=SIZE_PAGINATOR,
            )
        else:
            pages, self.page, visible_rows = _paged(rows, self.page, per_page)
            self._paginator = draw_paginator(
                draw, strip, self.page, pages,
                ctx.fonts, ctx.theme, size=SIZE_PAGINATOR,
            )
        self._rows = []
        for i, row in enumerate(visible_rows):
            self._draw_row(draw, ctx, row, y0 + FORM_PAGE_MARGIN + i * ROW_H,
                           x0, x1)
        return True

    def _draw_row(self, draw, ctx: Ctx, row: Row, y0: int, x0: int,
                  x1: int) -> None:
        theme = ctx.theme
        fonts = ctx.fonts
        top, bottom = y0, y0 + ROW_H  # one band: every glyph shares a centre
        label = truncate(fonts, row.label.upper(), 340, size=SIZE_FORM)
        fonts.draw_text(draw, (x0 + 12, text_y(fonts, label, top, bottom,
                                               size=SIZE_FORM)),
                        label, "regular", SIZE_FORM, theme.dim)
        control = getattr(self, f"_row_{row.kind}", self._row_info)
        control(draw, ctx, row, top, bottom, x1)

    # --- row controls (one method per Row.kind) ------------------------------

    def _row_info(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                  x1: int) -> None:
        self._read_only(draw, ctx, row, top, bottom, x1,
                        str(row.value), ctx.theme.fg)

    def _row_text(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                  x1: int) -> None:
        # read-only on the device, editable on the web — say so, and
        # reserve the hint's width before truncating so the two can
        # never overprint each other
        self._read_only(draw, ctx, row, top, bottom, x1, str(row.value),
                        ctx.theme.dim, hint="(web)")

    def _read_only(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                   x1: int, value: str, color, hint: str = "") -> None:
        fonts = ctx.fonts
        hint_w = fonts.textwidth(hint, "regular", SIZE_FORM) + 16 if hint else 0
        shown = truncate(fonts, value, x1 - 24 - hint_w, size=SIZE_FORM)
        width = fonts.textwidth(shown, "regular", SIZE_FORM)
        ty = text_y(fonts, shown, top, bottom, size=SIZE_FORM)
        fonts.draw_text(draw, (x1 - 12 - width, ty), shown, "regular",
                        SIZE_FORM, color)
        if hint:
            fonts.draw_text(draw, (x1 - 12 - width - hint_w, ty), hint,
                            "regular", SIZE_FORM, ctx.theme.dim)

    def _row_bool(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                  x1: int) -> None:
        # plain box; on = a white X, no inverse video
        rect = draw_button_auto(
            draw, x1 - 12, top + 4, ROW_H - 8,
            "X" if row.value else " ", ctx.fonts, ctx.theme, size=SIZE_FORM,
            min_width=44,
        )
        self._rows.append((rect, row.key, "toggle"))

    def _row_choice(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                    x1: int) -> None:
        rect = draw_button_auto(
            draw, x1 - 12, top + 4, ROW_H - 8,
            f"{self.value_text(row)} [next ›]", ctx.fonts, ctx.theme,
            size=SIZE_FORM,
        )
        self._rows.append((rect, row.key, "cycle"))

    def _row_int(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                 x1: int) -> None:
        fonts = ctx.fonts
        theme = ctx.theme
        value = self.value_text(row)
        step_w = self._stepper_width(fonts)
        value_w = fonts.textwidth(value, "regular", SIZE_FORM)
        plus = (x1 - 12 - step_w, top + 4, x1 - 12, bottom - 4)
        minus = (plus[0] - value_w - 24 - step_w, top + 4,
                 plus[0] - value_w - 24, bottom - 4)
        draw_button(draw, minus, "-", fonts, theme, size=SIZE_FORM)
        draw_button(draw, plus, "+", fonts, theme, size=SIZE_FORM)
        fonts.draw_text(draw, (plus[0] - 12 - value_w,
                               text_y(fonts, value, top, bottom,
                                      size=SIZE_FORM)),
                        value, "regular", SIZE_FORM, theme.fg)
        self._rows.append((minus, row.key, "minus"))
        self._rows.append((plus, row.key, "plus"))

    def _row_time(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                  x1: int) -> None:
        fonts = ctx.fonts
        theme = ctx.theme
        value = self.value_text(row)
        step_w = self._stepper_width(fonts)
        text_w = fonts.textwidth(value, "regular", SIZE_FORM)
        pair = 2 * step_w + 8
        left = x1 - 12 - (text_w + 14 + pair + 14 + pair)
        fonts.draw_text(draw, (left, text_y(fonts, value, top, bottom,
                                            size=SIZE_FORM)),
                        value, "regular", SIZE_FORM, theme.fg)
        blanks = ("hour-", "hour+", "minute-", "minute+")
        cursor = left + text_w + 14
        for index, action in enumerate(blanks):
            rect = (cursor, top + 4, cursor + step_w, bottom - 4)
            draw_button(draw, rect, "-" if action.endswith("-") else "+",
                        fonts, theme, size=SIZE_FORM)
            self._rows.append((rect, row.key, action))
            cursor += step_w + (8 if index % 2 == 0 else 14)

    def _stepper_width(self, fonts) -> int:
        """Both - and + buttons share this width — always equal."""
        return max(fonts.textwidth("+", "regular", SIZE_FORM),
                   fonts.textwidth("-", "regular", SIZE_FORM)) + 24

    # --- taps ---------------------------------------------------------------

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        for (rx0, ry0, rx1, ry1), key, action in self._rows:
            if rx0 <= x < rx1 and ry0 <= y < ry1:
                return self._apply(action, key, ctx)
        if self.scroll:
            return self._tap_scroller(x, y)
        return self._tap_paginator(x, y)

    def _apply(self, action: str, key: str, ctx: Ctx) -> bool:
        """Run one row control's action; True when the tap was consumed."""
        row = next((r for r in self.rows(ctx) if r.key == key), None)
        if row is None:  # the row vanished between render and tap
            return False
        value = row.value
        if action == "select":
            if self.on_select:
                self.on_select(row, ctx)
            return True
        spec = row.spec or {}
        if action == "toggle":
            new = toggle_bool(spec, value)
        elif action == "cycle":
            new = cycle_choice(spec, value)
        elif action.startswith(("hour", "minute")):
            part = "hour" if action.startswith("hour") else "minute"
            new = step_time(value, part, 1 if action.endswith("+") else -1)
        else:
            new = step_int(spec, value, 1 if action == "plus" else -1)
            if new == value:  # already at the bound: nothing to save
                return True
        if self.on_change:
            self.on_change(row, new, ctx)
        return True


class PickerView(ListView):
    """A modal picker: one row per option, tap to pick and pop back.

    `options` is a list of strings or (value, label) pairs.  The current
    value is marked with '>'; on_pick(value, ctx) runs before the view
    pops itself, so the caller keeps drawing the frame below.
    """

    def __init__(
        self,
        title: str,
        options: Iterable,
        on_pick: Callable[[Any, Ctx], None],
        current: Any = None,
    ) -> None:
        super().__init__(title, self._build(options, current))
        self.on_pick = on_pick
        # row keys are strings (the tap hitbox is keyed by string), so
        # the value map must be keyed the same way
        self._pick: dict[str, Any] = {
            str(value): value for value, _label in self._options(options)
        }

    @staticmethod
    def _options(options: Iterable) -> list[tuple[Any, str]]:
        pairs = []
        for option in options:
            if isinstance(option, (tuple, list)) and len(option) == 2:
                pairs.append((option[0], str(option[1])))
            else:
                pairs.append((option, str(option)))
        return pairs

    def _build(self, options: Iterable, current: Any) -> list[Row]:
        return [Row(key=str(value), label=label, value=value, kind="select")
                for value, label in self._options(options)
                if value != current]

    def _row_select(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                    x1: int) -> None:
        """A picker row is a full-width button: the whole line is the target."""
        rect = draw_button(draw, (ctx.content[0] + FORM_PAGE_MARGIN, top + 2,
                                  x1 - FORM_PAGE_MARGIN, bottom - 2),
                           row.label, ctx.fonts, ctx.theme, size=SIZE_FORM)
        self._rows.append((rect, row.key, "select"))

    def _apply(self, action: str, key: str, ctx: Ctx) -> bool:
        if action != "select":
            return False
        self.on_pick(self._pick.get(key), ctx)
        ctx.nav.pop()
        return True


class ConfirmView(ListView):
    """A modal yes/no dialog: the list primitive with two full-width rows.

    on_confirm() runs on "yes"; the view pops itself either way, so a
    module never has to know how the dialog was built.
    """

    def __init__(self, title: str, message: str,
                 on_confirm: Callable[[Ctx], None],
                 confirm_label: str = "yes",
                 cancel_label: str = "cancel") -> None:
        super().__init__(title, [
            Row("no", cancel_label, kind="select"),
            Row("yes", confirm_label, kind="select"),
        ])
        self.message = message
        self.on_confirm = on_confirm

    def _header_h(self, ctx: Ctx) -> int:
        return ROW_H

    def _draw_header(self, draw, ctx: Ctx) -> None:
        fonts = ctx.fonts
        x0, y0, x1, _y1 = ctx.content
        message = truncate(fonts, self.message, x1 - x0 - 24, size=SIZE_FORM)
        fonts.draw_text(draw, (x0 + 12,
                               text_y(fonts, message, y0, y0 + ROW_H,
                                      size=SIZE_FORM)),
                        message, "regular", SIZE_FORM, ctx.theme.fg)

    def _row_select(self, draw, ctx: Ctx, row: Row, top: int, bottom: int,
                    x1: int) -> None:
        rect = draw_button(draw, (ctx.content[0] + FORM_PAGE_MARGIN, top + 2,
                                  x1 - FORM_PAGE_MARGIN, bottom - 2),
                           row.label, ctx.fonts, ctx.theme, size=SIZE_FORM,
                           pressed=(row.key == "yes"))
        self._rows.append((rect, row.key, "select"))

    def _apply(self, action: str, key: str, ctx: Ctx) -> bool:
        if action != "select":
            return False
        if key == "yes":
            self.on_confirm(ctx)
        ctx.nav.pop()
        return True


class FormView(ListView):
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
        self.schema = schema
        self.get_values = get_values
        self.set_value = set_value
        super().__init__(title, self._fields)

    def _fields(self, ctx: Ctx) -> list[Row]:
        """One Row per visible schema field — hidden fields never render."""
        values = self.get_values()
        rows = []
        for key, spec in self.schema.items():
            if not visible(spec, values):
                continue
            value = values.get(key)
            if spec.get("write_only") and value:
                value = "set"  # the panel never reveals a stored secret
            rows.append(Row(key=key, label=spec.get("title", key),
                            value=value, kind=spec.get("type", "text"),
                            spec=spec))
        return rows

    def on_change(self, row: Row, value: Any, ctx: Ctx) -> None:
        self.set_value(row.key, value)


class InfoView(ListView):
    """Read-only rows: dim labels left, live values right.

    Each value is fetched at render time, so it shows live data; taking
    over the list primitive means it pages like everything else instead
    of drawing off the bottom of the panel.  interval=1 is what makes
    the app re-render it — without it a page like UPTIME freezes at the
    value it had when it was opened.
    """

    interval = 1

    def __init__(self, title: str, rows: list[tuple[str, Callable[[], str]]]) -> None:
        super().__init__(title, [])
        self.entries = list(rows)  # (label, value_fn) — fetched per render

    def rows(self, ctx: Ctx) -> list[Row]:
        return [Row(key=label, label=label, value=value_fn(), kind="info")
                for label, value_fn in self.entries]

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        return self._tap_paginator(x, y)
