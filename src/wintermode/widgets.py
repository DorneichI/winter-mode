"""Pure-draw helpers every view and module builds on.

Terminal idiom: bordered boxes, inverse video for pressed/selected,
`[‹ prev] n/m [next ›]` pagination.  Nothing here knows about the app —
just PIL drawing plus hitbox math, all testable off-screen.
"""

from __future__ import annotations

import math

from wintermode.fonts import SIZE_CARD, SIZE_PAGINATOR, Fonts
from wintermode.theme import Theme

Rect = tuple[int, int, int, int]  # x0, y0, x1, y1


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


def draw_button(
    draw,
    rect: Rect,
    label: str,
    fonts: Fonts,
    theme: Theme,
    weight: str = "regular",
    size: int = SIZE_CARD,
    pressed: bool = False,
) -> Rect:
    """A bordered box with a centered label; pressed = inverse video."""
    x0, y0, x1, y1 = rect
    fill = theme.fg if pressed else theme.bg
    text_fill = theme.bg if pressed else theme.fg
    draw.rectangle(rect, fill=fill)
    draw.rectangle(rect, outline=theme.border)
    _, text_h = fonts.textsize(label, weight, size)
    text_x = x0 + (x1 - x0 - fonts.textwidth(label, weight, size)) / 2
    text_y = y0 + (y1 - y0 - text_h) / 2
    fonts.draw_text(draw, (text_x, text_y), label, weight, size, text_fill)
    return rect


def draw_button_auto(
    draw,
    anchor_x1: int,
    y0: int,
    height: int,
    label: str,
    fonts: Fonts,
    theme: Theme,
    weight: str = "regular",
    size: int = SIZE_CARD,
    pressed: bool = False,
    pad: int = 12,
    min_width: int = 40,
) -> Rect:
    """A right-anchored button sized to its label; returns its rect."""
    width = max(min_width, fonts.textwidth(label, weight, size) + 2 * pad)
    rect = (anchor_x1 - width, y0, anchor_x1, y0 + height)
    draw_button(draw, rect, label, fonts, theme, weight=weight, size=size,
                pressed=pressed)
    return rect


def draw_paginator(
    draw,
    strip: Rect,
    page: int,
    pages: int,
    fonts: Fonts,
    theme: Theme,
    size: int = SIZE_PAGINATOR,
) -> dict[str, Rect | None]:
    """Centered `[‹ prev]  n/m  [next ›]`; returns prev/next hitboxes."""
    x0, y0, x1, y1 = strip
    result: dict[str, Rect | None] = {"prev": None, "next": None}
    if pages <= 1:
        return result
    label_prev = "[‹ prev]"
    label_next = "[next ›]"
    counter = f"{page + 1}/{pages}"
    prev_w = fonts.textwidth(label_prev, "regular", size)
    next_w = fonts.textwidth(label_next, "regular", size)
    counter_w = fonts.textwidth(counter, "regular", size)
    total = prev_w + next_w + counter_w + 40
    cx = x0 + (x1 - x0) / 2
    _, text_h = fonts.textsize(label_prev, "regular", size)
    ty = y0 + (y1 - y0 - text_h) / 2

    prev_x = cx - total / 2
    counter_x = prev_x + prev_w + 20
    next_x = counter_x + counter_w + 20

    prev_color = theme.fg if page > 0 else theme.dim
    next_color = theme.fg if page < pages - 1 else theme.dim
    fonts.draw_text(draw, (prev_x, ty), label_prev, "regular", size,
                    prev_color)
    fonts.draw_text(draw, (counter_x, ty), counter, "regular", size,
                    theme.dim)
    fonts.draw_text(draw, (next_x, ty), label_next, "regular", size,
                    next_color)

    if page > 0:
        result["prev"] = (int(prev_x), y0, int(prev_x + prev_w), y1)
    if page < pages - 1:
        result["next"] = (int(next_x), y0, int(next_x + next_w), y1)
    return result
