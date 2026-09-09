"""Pagination math, buttons, and text truncation — off-screen."""

import pytest
from PIL import Image, ImageDraw

from wintermode.widgets import draw_button, draw_paginator, paginate, truncate


def test_paginate_math():
    assert paginate([], 0, 8) == (0, [])
    assert paginate(list(range(8)), 0, 8) == (1, list(range(8)))
    pages, items = paginate(list(range(17)), 0, 8)
    assert (pages, items) == (3, list(range(8)))
    _, items = paginate(list(range(17)), 1, 8)
    assert items == list(range(8, 16))
    _, items = paginate(list(range(17)), 2, 8)
    assert items == [16]


def test_paginate_rejects_nonpositive_page_size():
    with pytest.raises(ValueError):
        paginate([1], 0, 0)


def test_button_pressed_inverts_video(theme, fonts):
    canvas = Image.new("RGB", (200, 60), theme.bg)
    draw = ImageDraw.Draw(canvas)
    rect = (10, 10, 90, 50)
    draw_button(draw, rect, "GO", fonts, theme, pressed=True)
    # interior pixel: fg; border pixel: border color
    assert canvas.getpixel((50, 30)) == theme.fg
    assert canvas.getpixel((10, 10)) == theme.border
    draw_button(draw, (100, 10, 180, 50), "GO", fonts, theme, pressed=False)
    assert canvas.getpixel((140, 30)) == theme.bg


def test_button_returns_its_hitbox(theme, fonts):
    canvas = Image.new("RGB", (100, 100), theme.bg)
    draw = ImageDraw.Draw(canvas)
    rect = (5, 5, 95, 45)
    assert draw_button(draw, rect, "X", fonts, theme) == rect


def test_paginator_offers_prev_and_next_per_page(theme, fonts):
    canvas = Image.new("RGB", (400, 30), theme.bg)
    draw = ImageDraw.Draw(canvas)
    strip = (0, 0, 400, 30)
    # single page: no hitboxes
    assert draw_paginator(draw, strip, 0, 1, fonts, theme) == {
        "prev": None, "next": None}
    # first of three: next only
    boxes = draw_paginator(draw, strip, 0, 3, fonts, theme)
    assert boxes["prev"] is None and boxes["next"] is not None
    # last of three: prev only
    boxes = draw_paginator(draw, strip, 2, 3, fonts, theme)
    assert boxes["prev"] is not None and boxes["next"] is None
    # middle: both
    boxes = draw_paginator(draw, strip, 1, 3, fonts, theme)
    assert boxes["prev"] is not None and boxes["next"] is not None


def test_truncate_fits_within_max_width(fonts):
    text = "A" * 100
    cut = truncate(fonts, text, 300, size=16)
    assert cut.endswith("..")
    assert len(cut) < len(text)
    assert fonts.textwidth(cut, "regular", 16) <= 300


def test_truncate_leaves_short_text_alone(fonts):
    assert truncate(fonts, "hello", 300, size=16) == "hello"
