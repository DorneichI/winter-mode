"""The Button model and the pure-draw helpers every view builds on.

One Button is a clickable shape (Rect or Circle) with an optional
border and an optional label; `tap()` turns a list of (Button, action)
pairs into hit-testing.  Nothing here knows about the app — just PIL
drawing plus geometry, all testable off-screen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeVar

from wintermode.fonts import SIZE_CARD, SIZE_PAGINATOR, Fonts
from wintermode.theme import Theme


def paginate(items: list, page: int, page_size: int) -> tuple[int, list]:
    """(page count, items on page `page`)."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    pages = math.ceil(len(items) / page_size) if items else 0
    start = page * page_size
    return pages, items[start : start + page_size]


def truncate(fonts: Fonts, text: str, max_width: int, weight: str = "regular",
             size: int = 16) -> str:
    """Cut `text` to fit max_width, appending '..' when truncated."""
    if fonts.textwidth(text, weight, size) <= max_width:
        return text
    while text and fonts.textwidth(text + "..", weight, size) > max_width:
        text = text[:-1]
    return text + ".."


def text_y(fonts: Fonts, text: str, y0: float, y1: float, weight: str = "regular",
           size: int = SIZE_CARD) -> float:
    """The `draw_text` y that centers `text` in the band y0..y1.

    Thin wrapper over Fonts.center_y, which owns the metrics: never
    hand-roll `(y1 - y0 - 26) // 2` — that is how the stepper's value
    ended up sitting at the top of its buttons.
    """
    return fonts.center_y(text, weight, size, y0, y1)


# --- the Button model -------------------------------------------------------


@dataclass(frozen=True)
class Rect:
    """A half-open rectangle hit shape: x0 <= x < x1, as it always was."""

    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def __iter__(self):
        yield from (self.x0, self.y0, self.x1, self.y1)


@dataclass(frozen=True)
class Circle:
    """A circular hit shape; the boundary belongs to the circle."""

    cx: float
    cy: float
    r: float

    def contains(self, x: float, y: float) -> bool:
        return (x - self.cx) ** 2 + (y - self.cy) ** 2 <= self.r ** 2

    def center(self) -> tuple[float, float]:
        return (self.cx, self.cy)


Shape = Rect | Circle


def _draw_circle(draw, center, radius, fill, outline=None, width: int = 3):
    """A filled circle at `center`; the Button circle-border primitive."""
    x, y = center
    rect = (int(x - radius), int(y - radius), int(x + radius), int(y + radius))
    draw.ellipse(rect, fill=fill, outline=outline, width=width)


@dataclass
class Button:
    """One clickable thing: a hit shape, an optional border, an optional label.

    `border=True` (the default) draws the outline along the hit shape;
    `None`/`False` draws none; an explicit Shape overrides — the map's
    station button hits at HIT_PAD radius but paints only its small dot.
    Disabled buttons are drawn dim and `contains()` is False, so a
    caller can keep them in the list without guarding every tap.
    """

    hit: Shape
    label: str | None = None
    border: Shape | bool | None = True
    weight: str = "regular"
    size: int = SIZE_CARD
    enabled: bool = True
    pressed: bool = False
    border_color: str = "border"  # theme token: "border" | "fg" | "dim"
    border_width: int = 1

    def __post_init__(self) -> None:
        if self.border is True:
            self.border = self.hit

    def contains(self, x: float, y: float) -> bool:
        return self.enabled and self.hit.contains(x, y)

    def draw(self, draw, fonts: Fonts, theme: Theme) -> None:
        """Fill + optional outline + optional centered label.

        Disabled wins over pressed (dim box, dim text).  Pressed is
        inverse video.  Fill and outline paint the *border* shape, never
        the hit shape — a station button hits at radius 22 but its bg
        fill must not erase the track lines around its 8px dot.
        """
        if not self.enabled:
            fill, text_color, outline = theme.bg, theme.dim, theme.dim
        elif self.pressed:
            fill = theme.fg
            text_color, outline = theme.bg, getattr(theme, self.border_color)
        else:
            fill = theme.bg
            text_color, outline = theme.fg, getattr(theme, self.border_color)
        border = self.border
        if border is not None:
            if isinstance(border, Rect):
                rect = (int(border.x0), int(border.y0),
                        int(border.x1), int(border.y1))
                draw.rectangle(rect, fill=fill)
                draw.rectangle(rect, outline=outline, width=self.border_width)
            else:
                _draw_circle(draw, (border.cx, border.cy), border.r, fill=fill,
                             outline=outline, width=self.border_width)
        if self.label:
            self._draw_label(draw, fonts, text_color)

    def _draw_label(self, draw, fonts: Fonts, color) -> None:
        label = self.label
        if isinstance(self.hit, Rect):
            max_w = max(1, self.hit.x1 - self.hit.x0 - 12)
            label = truncate(fonts, label, max_w, self.weight, self.size)
            text_x = self.hit.x0 + (self.hit.x1 - self.hit.x0
                                    - fonts.textwidth(label, self.weight,
                                                      self.size)) / 2
            ty = text_y(fonts, label, self.hit.y0, self.hit.y1,
                        self.weight, self.size)
        else:
            cx, cy = self.hit.center()
            w, h = fonts.textsize(label, self.weight, self.size)
            text_x, ty = cx - w / 2, cy - h / 2
        fonts.draw_text(draw, (text_x, ty), label, self.weight, self.size,
                        color)


T = TypeVar("T")


def tap(buttons: list[tuple[Button, T]], x: float, y: float) -> T | None:
    """The action of the first button containing (x, y); None when none does.

    Disabled buttons never match, so views keep inert buttons in the
    list instead of tracking which rects are live.
    """
    for button, action in buttons:
        if button.contains(x, y):
            return action
    return None


def button_auto(anchor_x1: int, y0: int, height: int, label: str,
                fonts: Fonts, *, weight: str = "regular",
                size: int = SIZE_CARD, pressed: bool = False,
                enabled: bool = True, pad: int = 12,
                min_width: int = 40) -> Button:
    """A right-anchored button sized to its label; constructs, never draws."""
    width = max(min_width, fonts.textwidth(label, weight, size) + 2 * pad)
    return Button(Rect(anchor_x1 - width, y0, anchor_x1, y0 + height), label,
                  weight=weight, size=size, pressed=pressed, enabled=enabled)


def paginator(draw, strip: tuple[int, int, int, int], page: int, pages: int,
              fonts: Fonts, theme: Theme, *,
              size: int = SIZE_PAGINATOR) -> list[tuple[Button, str]]:
    """Centered boxed `‹ prev` / `next ›` with a plain dim n/m between.

    Draws everything it returns.  pages <= 1 draws nothing (no counter
    either) and returns [].  A direction that cannot move is still drawn
    — dim and inert at the ends.
    """
    x0, y0, x1, y1 = strip
    if pages <= 1:
        return []
    prev_w = max(40, fonts.textwidth("‹ prev", "regular", size) + 24)
    next_w = max(40, fonts.textwidth("next ›", "regular", size) + 24)
    counter = f"{page + 1}/{pages}"
    counter_w = fonts.textwidth(counter, "regular", size)
    total = prev_w + next_w + counter_w + 40
    cx = x0 + (x1 - x0) / 2
    cursor = cx - total / 2
    prev = Button(Rect(cursor, y0, cursor + prev_w, y1), "‹ prev", size=size,
                  enabled=page > 0)
    prev.draw(draw, fonts, theme)
    cursor += prev_w + 20
    fonts.draw_text(draw, (cursor, text_y(fonts, counter, y0, y1, size=size)),
                    counter, "regular", size, theme.dim)
    cursor += counter_w + 20
    nxt = Button(Rect(cursor, y0, cursor + next_w, y1), "next ›", size=size,
                 enabled=page < pages - 1)
    nxt.draw(draw, fonts, theme)
    return [(prev, "prev"), (nxt, "next")]


def scroller(draw, strip: tuple[int, int, int, int], offset: int,
             visible: int, total: int, fonts: Fonts, theme: Theme, *,
             size: int = SIZE_PAGINATOR) -> list[tuple[Button, str]]:
    """Centered boxed `▲` / `▼`; [] (draws nothing) when neither moves.

    The direction that cannot scroll is drawn dim and inert.
    """
    x0, y0, x1, y1 = strip
    can_up = offset > 0
    can_down = offset + visible < total
    if not (can_up or can_down):
        return []
    up_w = max(40, fonts.textwidth("▲", "regular", size) + 24)
    down_w = max(40, fonts.textwidth("▼", "regular", size) + 24)
    total_w = up_w + down_w + 20
    cx = x0 + (x1 - x0) / 2
    cursor = cx - total_w / 2
    up = Button(Rect(cursor, y0, cursor + up_w, y1), "▲", size=size,
                enabled=can_up)
    up.draw(draw, fonts, theme)
    cursor += up_w + 20
    down = Button(Rect(cursor, y0, cursor + down_w, y1), "▼", size=size,
                  enabled=can_down)
    down.draw(draw, fonts, theme)
    return [(up, "up"), (down, "down")]
