"""The skeleton modules: clock, dummy, and the settings hub."""

import time

from PIL import Image, ImageDraw

from wintermode.context import BarItem
from wintermode.modules.clock.module import Clock
from wintermode.modules.dummy.module import Dummy
from wintermode.modules.settings.module import Settings
from wintermode.registry import Registry


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


# --- dummy ------------------------------------------------------------------


def test_dummy_tap_bumps_count_and_saves_config(theme, fonts, ctx, config):
    dummy = Dummy()
    registry = setup_registry(config, dummy)
    ctx = ctx(registry=registry)
    canvas, draw = make_canvas(theme)
    dummy.render(draw, ctx)
    before = config.generation
    assert dummy.on_tap(400, 300, ctx) is True
    assert config.data["dummy"]["count"] == 1
    assert config.generation == before + 1


def test_dummy_reset_action_zeroes_count(theme, fonts, ctx, config):
    dummy = Dummy()
    registry = setup_registry(config, dummy)
    ctx = ctx(registry=registry)
    dummy.on_tap(400, 300, ctx)
    dummy.on_action("reset", ctx)
    assert config.data["dummy"]["count"] == 0
    # unknown actions are ignored
    dummy.on_action("nope", ctx)
    assert config.data["dummy"]["count"] == 0


def test_dummy_status_item_tracks_count(theme, fonts, ctx, config):
    dummy = Dummy()
    registry = setup_registry(config, dummy)
    ctx = ctx(registry=registry)
    dummy.on_tap(400, 300, ctx)
    (item,) = dummy.status_items(ctx)
    assert item == BarItem("count 1")


def test_dummy_schema_has_all_four_dsl_types():
    assert {spec["type"] for spec in Dummy.config_schema.values()} == {
        "bool", "choice", "int", "text"}


# --- settings hub -----------------------------------------------------------


def test_settings_hub_cards_include_device_and_module_pages(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Dummy(), settings)
    ctx = ctx(registry=registry)
    labels = [label for label, _ in settings.cards(ctx)]
    assert labels[:3] == ["DISPLAY", "STATUS BAR", "SYSTEM"]
    assert "CLOCK" in labels  # no ▸ — that glyph is missing from 3270
    assert "DUMMY" in labels


def test_settings_statusbar_schema_lists_other_modules_plus_rotation(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Dummy(), settings)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    view = settings._views["statusbar"]
    assert set(view.schema) == {"clock", "dummy", "rotate_seconds"}


def test_settings_display_page_merges_theme_and_behavior(
        theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Dummy(), settings)
    ctx = ctx(registry=registry)
    settings.cards(ctx)
    view = settings._views["display"]
    assert set(view.schema) == {"theme", "light_from", "light_to",
                                "mode", "idle_seconds"}


def test_settings_module_card_tap_pushes_form(theme, fonts, ctx, config):
    settings = Settings()
    registry = setup_registry(config, Clock(), Dummy(), settings)
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
