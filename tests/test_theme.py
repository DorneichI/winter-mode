"""Theme tokens, the font cache, and the 1-bit text path."""

import pytest
from PIL import Image, ImageDraw

from wintermode.fonts import (
    CLEAN_SIZES,
    SIZE_BAR,
    SIZE_BOOT_VERSION,
    SIZE_CARD,
    SIZE_CLOCK,
    SIZE_FORM,
    SIZE_PAGINATOR,
    Fonts,
)
from wintermode.theme import THEMES, resolve


def test_themes_are_exactly_dark_light_night():
    assert set(THEMES) == {"dark", "light", "night"}


def test_tokens_are_valid_rgb_triples():
    for theme in THEMES.values():
        for token in (theme.bg, theme.fg, theme.accent, theme.dim, theme.border):
            assert len(token) == 3
            assert all(isinstance(c, int) and 0 <= c <= 255 for c in token)


def test_night_palette_is_warm_and_distinct():
    night = THEMES["night"]
    assert night.bg != THEMES["dark"].bg
    assert night.fg[0] > night.fg[2]  # redder than blue
    assert night.fg[1] > night.fg[2]  # green warmer than blue


def test_resolve_unknown_falls_back_to_dark(caplog):
    assert resolve("nope") is THEMES["dark"]
    assert "unknown theme" in caplog.text


def test_font_cache_returns_same_instance_per_size_and_weight():
    fonts = Fonts()
    assert fonts.get("regular", 16) is fonts.get("regular", 16)
    assert fonts.get("regular", 16) is not fonts.get("regular", 22)
    assert fonts.get("regular", 16) is not fonts.get("bold", 16)


def test_font_cache_rejects_unknown_weight():
    with pytest.raises(KeyError):
        Fonts().get("italic", 16)


def test_textwidth_is_monotonic_in_size():
    fonts = Fonts()
    assert fonts.textwidth("WINTER MODE", "regular", 40) > fonts.textwidth(
        "WINTER MODE", "regular", 20
    )


def test_named_sizes_are_all_verified_clean():
    for size in (SIZE_BAR, SIZE_CARD, SIZE_FORM, SIZE_PAGINATOR,
                 SIZE_CLOCK, SIZE_BOOT_VERSION):
        assert size in CLEAN_SIZES


def test_draw_text_is_strictly_bilevel(theme, fonts):
    canvas = Image.new("RGB", (300, 60), theme.bg)
    draw = ImageDraw.Draw(canvas)
    fonts.draw_text(draw, (5, 5), "WINTER 16:42", "regular", SIZE_BAR,
                    theme.fg)
    colors = {color for _count, color in canvas.getcolors()}
    assert colors <= {theme.bg, theme.fg}  # no anti-aliased grays


def test_draw_text_scales_non_clean_sizes_and_stays_bilevel(theme, fonts):
    canvas = Image.new("RGB", (200, 60), theme.bg)
    draw = ImageDraw.Draw(canvas)
    fonts.draw_text(draw, (5, 5), "W", "regular", 30, theme.fg)  # not clean
    colors = {color for _count, color in canvas.getcolors()}
    assert colors <= {theme.bg, theme.fg}


def test_draw_text_empty_text_is_a_noop(theme, fonts):
    canvas = Image.new("RGB", (50, 50), theme.bg)
    draw = ImageDraw.Draw(canvas)
    fonts.draw_text(draw, (0, 0), "", "regular", SIZE_BAR, theme.fg)
    assert {c for _n, c in canvas.getcolors()} == {theme.bg}
