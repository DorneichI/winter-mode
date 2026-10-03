"""Pagination math, the Button model, and text truncation — off-screen."""

import pytest
from PIL import Image, ImageDraw

from wintermode.widgets import (
    Button,
    Circle,
    Rect,
    button_auto,
    paginate,
    paginator,
    tap,
    truncate,
)


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
    Button(Rect(10, 10, 90, 50), "GO", pressed=True).draw(draw, fonts, theme)
    # interior pixel: fg; border pixel: border color
    assert canvas.getpixel((50, 30)) == theme.fg
    assert canvas.getpixel((10, 10)) == theme.border
    Button(Rect(100, 10, 180, 50), "GO").draw(draw, fonts, theme)
    assert canvas.getpixel((140, 30)) == theme.bg


def test_button_border_defaults_to_its_hit(theme, fonts):
    button = Button(Rect(5, 5, 95, 45), "X")
    assert button.hit == Rect(5, 5, 95, 45)
    assert button.border == button.hit


def test_disabled_button_is_dim_and_inert(theme, fonts):
    canvas = Image.new("RGB", (100, 100), theme.bg)
    draw = ImageDraw.Draw(canvas)
    button = Button(Rect(10, 10, 90, 50), "GO", enabled=False)
    button.draw(draw, fonts, theme)
    assert canvas.getpixel((50, 30)) == theme.bg
    assert canvas.getpixel((10, 10)) == theme.dim
    assert not button.contains(50, 30)


def test_button_auto_sizes_to_label(theme, fonts):
    button = button_auto(200, 0, 40, "MODE", fonts)
    width = max(40, fonts.textwidth("MODE", "regular", 26) + 24)
    assert button.hit.x1 == 200
    assert button.hit.x1 - button.hit.x0 == width


def test_circle_hit_contains():
    button = Button(Circle(50, 50, 10))
    assert button.contains(50, 50)
    assert button.contains(50, 60)  # the boundary belongs to the circle
    assert not button.contains(50, 61)


def test_tap_returns_first_matching_action():
    a = Button(Rect(0, 0, 50, 50))
    b = Button(Rect(0, 0, 100, 100))
    assert tap([(a, "a"), (b, "b")], 25, 25) == "a"
    assert tap([(b, "b"), (a, "a")], 25, 25) == "b"  # first match wins
    assert tap([(a, "a")], 60, 60) is None


def test_paginator_offers_prev_and_next_per_page(theme, fonts):
    canvas = Image.new("RGB", (400, 30), theme.bg)
    draw = ImageDraw.Draw(canvas)
    strip = (0, 0, 400, 30)

    def states(boxes):
        return {action: button.enabled for button, action in boxes}

    # single page: nothing drawn, no buttons
    assert paginator(draw, strip, 0, 1, fonts, theme) == []
    # first of three: next only
    assert states(paginator(draw, strip, 0, 3, fonts, theme)) == {
        "prev": False, "next": True}
    # last of three: prev only
    assert states(paginator(draw, strip, 2, 3, fonts, theme)) == {
        "prev": True, "next": False}
    # middle: both
    assert states(paginator(draw, strip, 1, 3, fonts, theme)) == {
        "prev": True, "next": True}


def test_truncate_fits_within_max_width(fonts):
    text = "A" * 100
    cut = truncate(fonts, text, 300, size=16)
    assert cut.endswith("..")
    assert len(cut) < len(text)
    assert fonts.textwidth(cut, "regular", 16) <= 300


def test_truncate_leaves_short_text_alone(fonts):
    assert truncate(fonts, "hello", 300, size=16) == "hello"
