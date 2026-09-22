"""The skeleton modules: clock, boston, and the settings hub."""

import time

from PIL import Image, ImageDraw

from wintermode.config import UPDATES_SCHEMA
from wintermode.modules.boston.module import Boston
from wintermode.modules.clock.module import Clock
from wintermode.modules.settings.module import Settings
from wintermode.registry import Registry
from wintermode.views import InfoView


def make_canvas(theme):
    image = Image.new("RGB", (800, 480), theme.bg)
    return image, ImageDraw.Draw(image)


def setup_registry(config, *modules):
    registry = Registry(list(modules), config)
    registry.validate_namespaces()
    return registry


# --- clock ------------------------------------------------------------------


def test_clock_render_is_idempotent_within_a_second(theme, fonts, ctx, config):
    clock = Clock()
    registry = setup_registry(config, clock)
    ctx = ctx(registry=registry, wall=1_700_000_000.0)
    _canvas, draw = make_canvas(theme)
    assert clock.render(draw, ctx) is True
    assert clock.render(draw, ctx) is False  # same second, nothing changed


def test_clock_renders_pixels_inside_content(theme, fonts, ctx, config):
    clock = Clock()
    registry = setup_registry(config, clock)
    ctx = ctx(registry=registry, wall=1_700_000_000.0)
    canvas, draw = make_canvas(theme)
    clock.render(draw, ctx)
    # the bar region above the content must stay untouched
    colors = {c for _n, c in canvas.crop((0, 0, 800, 30)).getcolors()}
    assert colors <= {theme.bg}


def test_clock_publishes_date_item(theme, fonts, ctx, config):
    clock = Clock()
    registry = setup_registry(config, clock)
    ctx = ctx(registry=registry, wall=1_700_000_000.0)
    items = clock.status_items(ctx)
    assert len(items) == 1
    assert items[0].text == time.strftime("%d.%m.%Y",
                                          time.localtime(1_700_000_000.0))


# --- settings hub -----------------------------------------------------------


def test_settings_hub_cards_include_device_and_module_pages(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Boston(), settings)
    ctx = ctx(registry=registry)
    labels = [label for label, _ in settings.cards(ctx)]
    assert labels[:2] == ["DISPLAY", "STATUS BAR"]
    assert "UPDATES" in labels
    assert "SYSTEM" in labels
    assert "CLOCK" in labels  # no ▸ — that glyph is missing from 3270
    assert "BOSTON" in labels


def test_settings_statusbar_schema_lists_other_modules_plus_rotation(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Boston(), settings)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    view = settings._device_views["statusbar"]
    # the hub itself publishes no status items, so it gets no toggle —
    # and the web API serves this exact schema (wintermode.device)
    assert set(view.schema) == {"clock", "boston", "rotate_seconds"}
    assert "settings" not in view.schema


def test_settings_display_page_merges_theme_and_behavior(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Boston(), settings)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    view = settings._device_views["display"]
    assert set(view.schema) == {"theme", "light_from", "light_to",
                                "mode", "idle_seconds"}


def test_settings_updates_page_has_the_auto_toggle_schema(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Boston(), settings)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    view = settings._device_views["updates"]
    assert view.schema == UPDATES_SCHEMA


def test_settings_updates_toggle_writes_the_root_key(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Boston(), settings)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    view = settings._device_views["updates"]
    _canvas, draw = make_canvas(theme)
    view.render(draw, ctx)
    for rect, key, action in view._rows:
        if key == "auto" and action == "toggle":
            x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            assert view.on_tap(x, y, ctx) is True
            assert config.data["updates"]["auto"] is False
            return
    raise AssertionError("no toggle row for 'auto'")


def test_settings_module_view_is_not_shadowed_by_a_device_page(
        theme, fonts, ctx, config, fake_module):
    """A module whose id matches a device page still gets its own form."""
    settings = Settings()
    system = fake_module("system")
    system.config_schema = {"level": {"type": "int", "title": "Level",
                                      "default": 3}}
    registry = setup_registry(config, Clock(), Boston(), settings, system)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    settings.cards(ctx)  # a second render must not swap the two
    assert settings._module_views["system"].schema == system.config_schema
    # the device page under the same name is still the SYSTEM info view
    assert isinstance(settings._device_views["system"], InfoView)


def test_settings_module_card_tap_pushes_form(theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Boston(), settings)
    ctx = ctx(registry=registry)
    cards = settings.cards(ctx)
    clock_card = next(t for label, t in cards if label == "CLOCK")
    assert len(ctx.nav) == 1
    settings.on_card(clock_card, ctx)
    assert len(ctx.nav) == 2
    assert ctx.nav.top.title == "CLOCK"


def test_display_page_times_are_conditional_on_auto():
    from wintermode.config import DISPLAY_PAGE_SCHEMA
    for key in ("light_from", "light_to"):
        assert DISPLAY_PAGE_SCHEMA[key]["visible_if"] == {
            "field": "theme", "equals": "auto"}


def test_idle_seconds_is_conditional_on_wake_on_touch():
    from wintermode.config import DISPLAY_PAGE_SCHEMA
    assert DISPLAY_PAGE_SCHEMA["idle_seconds"]["visible_if"] == {
        "field": "mode", "equals": "wake_on_touch"}
