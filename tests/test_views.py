"""Framework views: card grids, auto-generated forms, info rows."""

from PIL import Image, ImageDraw

from wintermode.views import CARD_PAGE_SIZE, FormView, HomeView, InfoView


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
    registry = registry(["clock", "boston"])
    view, canvas, ctx = render_home(theme, fonts, ctx, registry=registry)
    cards = view._cards()
    assert [label for label, _ in cards] == ["SETTINGS", "CLOCK", "BOSTON"]


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


# --- FormView -------------------------------------------------------------

SCHEMA = {
    "flag": {"type": "bool", "title": "Flag", "default": False},
    "mode": {"type": "choice", "title": "Mode",
             "options": ["count", "wave"], "default": "count"},
    "count": {"type": "int", "title": "Count", "min": 0, "max": 5,
              "default": 0},
    "note": {"type": "text", "title": "Note", "default": "hello"},
}


def make_form(ctx):
    values = {"flag": False, "mode": "count", "count": 0, "note": "hello"}
    writes = []

    def set_value(key, value):
        writes.append((key, value))
        values[key] = value

    view = FormView("TEST", SCHEMA, lambda: dict(values), set_value)
    canvas, draw = make_canvas(ctx.theme)
    view.render(draw, ctx)
    return view, writes, values


def tap_row(view, ctx, key, action):
    for rect, row_key, row_action in view._rows:
        if row_key == key and row_action == action:
            x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            assert view.on_tap(x, y, ctx) is True
            return
    raise AssertionError(f"no {action!r} row for {key!r}")


def test_form_toggle_writes_once(theme, fonts, ctx):
    c = ctx(registry=None)
    view, writes, values = make_form(c)
    tap_row(view, c, "flag", "toggle")
    assert writes == [("flag", True)]
    assert values["flag"] is True


def test_form_choice_cycles(theme, fonts, ctx):
    c = ctx(registry=None)
    view, writes, values = make_form(c)
    tap_row(view, c, "mode", "cycle")
    assert writes == [("mode", "wave")]
    tap_row(view, c, "mode", "cycle")
    assert writes[-1] == ("mode", "count")  # wraps


def test_form_stepper_clamps_at_bounds(theme, fonts, ctx):
    c = ctx(registry=None)
    view, writes, values = make_form(c)
    tap_row(view, c, "count", "minus")  # already at 0: no write
    assert writes == []
    tap_row(view, c, "count", "plus")
    assert writes == [("count", 1)]


def test_form_text_row_is_read_only(theme, fonts, ctx):
    c = ctx(registry=None)
    view, writes, values = make_form(c)
    # the text row (4th field) has no hitbox: a tap over its value
    # area is unconsumed
    assert view.on_tap(750, 180, c) is False
    assert writes == []


def test_form_masks_write_only_values(theme, fonts, ctx):
    # a stored secret never reaches the panel: it renders as "set"
    c = ctx(registry=None)
    schema = {"key": {"type": "text", "title": "Key", "default": "",
                      "write_only": True}}
    view = FormView("T", schema, lambda: {"key": "hunter2"},
                    lambda key, value: None)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    (row,) = [r for r in view.rows(c) if r.key == "key"]
    assert row.value == "set"


def test_form_rows_fit_in_content(theme, fonts, ctx):
    c = ctx(registry=None)
    view, writes, values = make_form(c)
    for (x0, y0, x1, y1), _key, _action in view._rows:
        assert c.content[0] <= x0 and x1 <= c.content[2]
        assert c.content[1] <= y0 and y1 <= c.content[3]


# --- InfoView -------------------------------------------------------------


def test_infoview_draws_label_and_value(theme, fonts, ctx):
    ctx = ctx(registry=None)
    view = InfoView("DEVICE", [("VERSION", lambda: "0.1.0")])
    canvas, draw = make_canvas(theme)
    view.render(draw, ctx)
    row = canvas.crop((ctx.content[0], ctx.content[1] + 10,
                       ctx.content[2], ctx.content[1] + 46))
    colors = {c for _n, c in row.getcolors()}
    assert theme.dim in colors  # the label
    assert theme.fg in colors  # the value


def test_form_int_steppers_are_equal_size(theme, fonts, ctx):
    c = ctx(registry=None)
    view, _writes, _values = make_form(c)
    minus = plus = None
    for rect, key, action in view._rows:
        if key == "count" and action == "minus":
            minus = rect
        if key == "count" and action == "plus":
            plus = rect
    assert minus and plus
    assert minus[2] - minus[0] == plus[2] - plus[0]  # identical widths


def test_form_choice_label_says_next(theme, fonts, ctx):
    c = ctx(registry=None)
    view, _writes, values = make_form(c)
    view.render(ImageDraw.Draw(Image.new("RGB", (800, 480))), c)
    # the choice button sizes itself to its "[next ›]" label exactly
    for rect, key, _action in view._rows:
        if key == "mode":
            label = f"{values['mode']} [next ›]"
            expected = c.fonts.textwidth(label, "regular", 26) + 24
            assert rect[2] - rect[0] == expected
            return
    raise AssertionError("no cycle row")


def test_form_time_row_steps_and_wraps(theme, fonts, ctx):
    c = ctx(registry=None)
    schema = {"t": {"type": "time", "title": "Wake", "default": "07:00"}}
    values = {"t": "07:00"}
    writes = []

    def set_value(key, value):
        writes.append((key, value))
        values[key] = value

    view = FormView("T", schema, lambda: dict(values), set_value)
    view.render(ImageDraw.Draw(Image.new("RGB", (800, 480))), c)
    actions = {action for _r, _k, action in view._rows}
    assert actions == {"hour-", "hour+", "minute-", "minute+"}
    tap_row(view, c, "t", "minute+")
    assert writes == [("t", "07:05")]
    tap_row(view, c, "t", "hour-")
    assert writes[-1] == ("t", "06:05")


def test_form_hides_conditional_fields(theme, fonts, ctx):
    c = ctx(registry=None)
    schema = {
        "theme": {"type": "choice", "title": "Theme",
                  "options": ["dark", "auto"], "default": "dark"},
        "light_from": {"type": "time", "title": "Light from",
                       "default": "07:00",
                       "visible_if": {"field": "theme", "equals": "auto"}},
    }
    values = {"theme": "dark", "light_from": "07:00"}
    writes = []

    def set_value(key, value):
        writes.append((key, value))
        values[key] = value

    view = FormView("T", schema, lambda: dict(values), set_value)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    keys = {key for _rect, key, _action in view._rows}
    assert keys == {"theme"}  # light_from hidden while theme is dark

    tap_row(view, c, "theme", "cycle")  # -> auto
    view.render(draw, c)  # the app re-renders after a consumed tap
    keys = {key for _rect, key, _action in view._rows}
    assert keys == {"theme", "light_from"}  # now it appears

    # the value survives hidden periods — it is never deleted
    assert values["light_from"] == "07:00"
    assert writes == [("theme", "auto")]


def test_a_shrunken_page_clamps_before_slicing(theme, fonts, ctx):
    # the page index used to be clamped AFTER paginate() had sliced: a
    # collection that shrank under a stale page drew an empty frame
    from wintermode.views import _paged

    items = [1, 2, 3]
    pages, page, shown = _paged(items, 5, 10)
    assert (pages, page) == (1, 0)
    assert shown == items


def test_stale_page_renders_content_not_blank(theme, fonts, ctx, config):

    c = ctx(registry=None)
    view = FormView("T", SCHEMA, lambda: {}, lambda key, value: None)
    view.page = 3  # as if fields vanished while sitting on a later page
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    assert view.page == 0
    assert view._rows  # a stale index must not draw an empty page
    # every interactive field is on the page (the text row is read-only)
    assert {key for _rect, key, _action in view._rows} == {
        "flag", "mode", "count"}


def test_list_view_is_a_reusable_primitive(theme, fonts, ctx):
    from wintermode.views import ListView, Row

    rows = [Row("a", "Alpha", value=1, kind="int",
                spec={"min": 0, "max": 3}),
            Row("b", "Bravo", value="hi", kind="info")]
    writes = []
    view = ListView("DEMO", rows, on_change=lambda row, value, c:
                    writes.append((row.key, value)))
    c = ctx(registry=None)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    actions = {action for _r, _k, action in view._rows}
    assert actions == {"minus", "plus"}
    assert view.on_tap(759, 100, c) is False  # info row is inert
    plus = next(r for r, k, a in view._rows if a == "plus")
    assert view.on_tap((plus[0] + plus[2]) // 2, (plus[1] + plus[3]) // 2,
                       c) is True
    assert writes == [("a", 2)]
    assert view.title == "DEMO"


# --- ListView scroll mode ---------------------------------------------------


def make_scroll_view(ctx, count):
    from wintermode.views import ListView, Row

    # int rows carry hitboxes; inert info rows would never reach _rows
    rows = [Row(key=f"r{i}", label=f"row {i}", value=0, kind="int",
                spec={"min": 0, "max": 3})
            for i in range(count)]

    class ScrollList(ListView):
        scroll = True

    return ScrollList("SCROLL", rows)


def scroller_tap(view, ctx, direction):
    rect = view._scroller[direction]
    assert rect is not None, f"{direction} should be tappable"
    assert view.on_tap((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2,
                       ctx) is True


def test_scroll_list_shows_only_down_button_at_top(theme, fonts, ctx):
    c = ctx(registry=None)
    view = make_scroll_view(c, 15)  # 10 rows fit
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    assert view._scroller["down"] is not None
    assert view._scroller["up"] is None
    assert {key for _rect, key, _action in view._rows} == {
        f"r{i}" for i in range(10)}  # 10 of 15 rows on screen


def test_scroll_list_scrolls_one_row_per_tap(theme, fonts, ctx):
    c = ctx(registry=None)
    view = make_scroll_view(c, 15)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    scroller_tap(view, c, "down")
    view.render(draw, c)  # the loop re-renders after a consumed tap
    assert view._offset == 1
    assert {key for _rect, key, _action in view._rows} == {
        f"r{i}" for i in range(1, 11)}


def test_scroll_list_up_button_inert_at_top(theme, fonts, ctx):
    c = ctx(registry=None)
    view = make_scroll_view(c, 15)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    # a tap where the up button would sit is unconsumed at the top
    assert view._scroller["up"] is None


def test_scroll_list_ends_with_only_up_button(theme, fonts, ctx):
    c = ctx(registry=None)
    view = make_scroll_view(c, 15)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    for _ in range(5):
        scroller_tap(view, c, "down")
        view.render(draw, c)
    assert view._offset == 5  # 15 rows - 10 visible
    assert view._scroller["down"] is None
    assert view._scroller["up"] is not None
    assert {key for _rect, key, _action in view._rows} == {
        f"r{i}" for i in range(5, 15)}  # the tail is on screen


def test_scroll_list_without_overflow_has_no_buttons(theme, fonts, ctx):
    c = ctx(registry=None)
    view = make_scroll_view(c, 3)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    assert view._scroller == {"up": None, "down": None}
    # nothing in the scroller strip consumes a tap
    assert view.on_tap(400, 470, c) is False


def test_scroll_list_clamps_offset_before_slicing(theme, fonts, ctx):
    # a list that shrank under a stale offset must not render past its end
    c = ctx(registry=None)
    view = make_scroll_view(c, 15)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    view._offset = 9  # as if rows vanished while scrolled down
    from wintermode.views import Row

    view._rows_fn = lambda _ctx: [Row("r0", "row 0", kind="info")]
    view.render(draw, c)
    assert view._offset == 0
    assert view._scroller == {"up": None, "down": None}


def test_scroll_list_rows_still_fire_actions(theme, fonts, ctx):
    from wintermode.views import ListView, Row

    rows = [Row(key="a", label="Alpha", value=1, kind="int",
                spec={"min": 0, "max": 3})]

    class ScrollList(ListView):
        scroll = True

    writes = []
    view = ScrollList("S", rows, on_change=lambda row, value, c:
                      writes.append((row.key, value)))
    c = ctx(registry=None)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    plus = next(r for r, k, a in view._rows if a == "plus")
    assert view.on_tap((plus[0] + plus[2]) // 2, (plus[1] + plus[3]) // 2,
                       c) is True
    assert writes == [("a", 2)]


def test_picker_picks_and_pops(theme, fonts, ctx):
    from wintermode.views import PickerView

    c = ctx(registry=None)
    picked = []
    picker = PickerView("THEME", ["dark", "light"], lambda value, cc:
                        picked.append(value), current="dark")
    c.nav.push(picker)
    canvas, draw = make_canvas(theme)
    picker.render(draw, c)
    assert {key for _r, key, _a in picker._rows} == {"light"}  # current hidden
    rect = picker._rows[0][0]
    assert picker.on_tap((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2,
                         c) is True
    assert picked == ["light"]
    assert len(c.nav) == 1  # it popped itself


def test_picker_accepts_value_label_pairs(theme, fonts, ctx):
    from wintermode.views import PickerView

    c = ctx(registry=None)
    picker = PickerView("SIZE", [(26, "small"), (44, "large")],
                        lambda value, cc: None)
    canvas, draw = make_canvas(theme)
    picker.render(draw, c)
    assert {key for _r, key, _a in picker._rows} == {"26", "44"}
    assert picker._pick["44"] == 44


def test_confirm_view_confirms_and_pops(theme, fonts, ctx):
    from wintermode.views import ConfirmView

    c = ctx(registry=None)
    confirmed = []
    dialog = ConfirmView("RESET", "clear the counter?", lambda cc:
                         confirmed.append(True))
    c.nav.push(dialog)
    canvas, draw = make_canvas(theme)
    dialog.render(draw, c)
    assert {action for _r, _k, action in dialog._rows} == {"select"}
    no = next(r for r, k, _a in dialog._rows if k == "no")
    assert dialog.on_tap((no[0] + no[2]) // 2, (no[1] + no[3]) // 2, c) is True
    assert confirmed == []  # cancel does not confirm
    assert len(c.nav) == 1


def test_the_stepper_value_and_buttons_share_a_centre(theme, fonts, ctx):
    """The reported bug: "60" sat at the top of the boxes, not centered.

    Every glyph in a row is centered on the row band by one rule, so the
    value, the -/+ buttons and the label line up optically.
    """

    c = ctx(registry=None)
    view = FormView("T", {"count": {"type": "int", "title": "Count",
                                    "min": 0, "max": 99, "default": 60}},
                    lambda: {"count": 60}, lambda key, value: None)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)

    minus = next(r for r, k, a in view._rows if a == "minus")
    plus = next(r for r, k, a in view._rows if a == "plus")
    y0, y1 = minus[1], minus[3]
    band_centre = (y0 + y1) / 2

    def ink_centre(x_range):
        rows = range(y0 + 1, y1 - 1)  # inside the 1px border
        ys = [y for y in rows
              if any(canvas.getpixel((x, y)) != c.theme.bg for x in x_range)]
        return (min(ys) + max(ys)) / 2

    for label, x_range in (
        ("-", range(minus[0] + 4, minus[2] - 4)),
        ("+", range(plus[0] + 4, plus[2] - 4)),
        ("value", range(minus[2] + 2, plus[0] - 2)),
    ):
        assert abs(ink_centre(x_range) - band_centre) <= 2.5, label


def test_a_secret_row_ignores_its_stepper(theme, fonts, ctx, config):
    """A write_only row draws as "set", so a stepper's value is not the
    value it would write — the tap must do nothing, not crash."""
    spec = {"pin": {"type": "int", "title": "Pin", "default": 0, "max": 99,
                    "write_only": True}}
    config.update({"door": {"pin": 42}})
    view = FormView("DOOR", spec,
                    lambda: {"pin": config.namespace("door").get("pin")},
                    lambda key, value: config.update_module(
                        "door", {key: value}, spec))
    c = ctx(registry=None)
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    _rect, key, action = next(r for r in view._rows if r[2] == "plus")
    view.on_tap((_rect[0] + _rect[2]) // 2, (_rect[1] + _rect[3]) // 2, c)
    assert config.namespace("door")["pin"] == 42  # untouched


def test_a_scrolling_info_page_uses_its_scroller(theme, fonts, ctx):
    """InfoView inherits the scroll path: with scroll on, the [▼] it
    draws is the control that moves it."""

    class Long(InfoView):
        scroll = True

    c = ctx(registry=None)
    view = Long("LONG", [(f"row {i}", lambda i=i: str(i)) for i in range(15)])
    canvas, draw = make_canvas(theme)
    view.render(draw, c)
    rect = view._scroller["down"]
    assert rect is not None
    assert view.on_tap((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2,
                       c) is True
    assert view._offset == 1
