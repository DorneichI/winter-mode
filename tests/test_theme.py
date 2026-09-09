"""Theme tokens and font cache."""

import pytest

from wintermode.fonts import Fonts
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
