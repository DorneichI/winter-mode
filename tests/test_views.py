"""HomeView: the card grid, pagination, and tap-to-push."""

from PIL import Image, ImageDraw

from wintermode.views import CARD_PAGE_SIZE, HomeView


def make_canvas(theme):
    image = Image.new("RGB", (800, 480), theme.bg)
    return image, ImageDraw.Draw(image)


def render_home(theme, fonts, ctx_factory, registry=None, page=0):
    ctx = ctx_factory(registry=registry)
    view = HomeView(registry=registry, config=ctx.config)
    view.page = page
    canvas, draw = make_canvas(theme)
    view.render(draw, ctx)
    return view, canvas, ctx


def test_static_settings_card_when_no_settings_module(theme, fonts, ctx):
    _, canvas, ctx = render_home(theme, fonts, ctx)
    # the settings card is the first hitbox target
    assert list(ctx.nav.stack)[0].title == "HOME"
    assert len(HomeView(registry=None, config=None)._cards()) == 1


def test_cards_for_every_enabled_module(theme, fonts, ctx, registry):
    registry = registry(["clock", "dummy"])
    view, canvas, ctx = render_home(theme, fonts, ctx, registry=registry)
    cards = view._cards()
    assert [label for label, _ in cards] == ["SETTINGS", "CLOCK", "DUMMY"]


def test_cards_are_bordered_and_inside_content(theme, fonts, ctx, registry):
    registry = registry(["clock"])
    view, canvas, ctx = render_home(theme, fonts, ctx, registry=registry)
    rects = view._grid_rects(ctx)
    assert len(rects) == CARD_PAGE_SIZE
    cards = view._cards()
    for x0, y0, x1, y1 in rects[: len(cards)]:  # only occupied cells draw
        assert ctx.content[0] <= x0 and x1 <= ctx.content[2]
        assert ctx.content[1] <= y0 and y1 <= ctx.content[3]
        # the card border was drawn
        assert canvas.getpixel((x0, y0)) == theme.border


def test_grid_paginates_when_cards_exceed_one_page(
        theme, fonts, ctx, registry, fake_module, config):
    # 8 modules + the static SETTINGS card = 9 cards -> 2 pages
    modules = [fake_module(f"m{i:02d}") for i in range(CARD_PAGE_SIZE)]
    from wintermode.registry import Registry
    registry = Registry(modules, config)
    view, canvas, ctx = render_home(theme, fonts, ctx, registry=registry)
    assert view._paginator["next"] is not None
    assert view._paginator["prev"] is None
    assert len(view._hitboxes) == CARD_PAGE_SIZE

    # tap next -> the app loop re-renders -> page two shows one card
    nx0, ny0, nx1, ny1 = view._paginator["next"]
    assert view.on_tap((nx0 + nx1) // 2, (ny0 + ny1) // 2, ctx) is True
    assert view.page == 1
    view.render(ImageDraw.Draw(canvas), ctx)  # what the loop does next
    assert view._paginator["prev"] is not None
    assert len(view._hitboxes) == 1


def test_tapping_a_module_card_pushes_it(theme, fonts, ctx, registry):
    registry = registry(["clock"])
    view, canvas, ctx = render_home(theme, fonts, ctx, registry=registry)
    assert len(ctx.nav) == 1
    # the clock card is the second card (after static SETTINGS)
    cards = view._cards()
    clock_index = [label for label, _ in cards].index("CLOCK")
    rect = list(view._hitboxes)[clock_index]
    x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    assert view.on_tap(x, y, ctx) is True
    assert len(ctx.nav) == 2
    assert ctx.nav.top.id == "clock"


def test_tap_outside_cards_and_paginator_is_unconsumed(
        theme, fonts, ctx, registry):
    registry = registry(["clock"])
    view, canvas, ctx = render_home(theme, fonts, ctx, registry=registry)
    assert view.on_tap(799, 479, ctx) is False
