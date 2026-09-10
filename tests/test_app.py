"""Loop-level behavior with fake hardware: bar, stack, render-on-change."""

from wintermode.app import BAR_H
from wintermode.context import Nav
from wintermode.views import HomeView


def present(app, lcd) -> bool:
    """run()'s inner loop body, without the loop."""
    dirty = app._step()
    if dirty:
        lcd.image(app.canvas)
    return dirty


def test_first_step_renders_and_presents_once(make_app):
    app, lcd, _touch, _clock = make_app()
    assert present(app, lcd) is True
    assert len(lcd.calls) == 1
    # the first frame paints the home grid, not just the bar
    colors = {c for _n, c in app.canvas.crop((0, BAR_H, 800, 480)).getcolors()}
    assert app.theme.border in colors  # card borders are drawn


def test_first_frame_was_the_regression(make_app):
    # the bar tick used to be the only thing painted on frame one;
    # the content area must never stay blank at startup
    app, lcd, _touch, _clock = make_app()
    present(app, lcd)
    assert app.canvas.getpixel((400, 400)) == app.theme.bg  # background
    assert len(lcd.calls) == 1


def test_noop_step_presents_nothing(make_app):
    app, lcd, _touch, _clock = make_app()
    present(app, lcd)
    assert app._step() is False  # same second, no events, no stack change
    assert len(lcd.calls) == 1  # run() skips the blit


def test_second_boundary_redraws_bar(make_app):
    app, lcd, _touch, clock = make_app()
    present(app, lcd)
    clock.set(1001.0, 1_700_000_001.0)  # next wall-clock second
    assert present(app, lcd) is True
    assert len(lcd.calls) == 2


def test_bar_buttons_hidden_at_root_and_tap_is_ignored(make_app, point):
    app, lcd, touch, _clock = make_app()
    present(app, lcd)
    assert app._bar_hitboxes == []
    touch.script = [[point(790, 10)]]  # tap in the bar region at root
    assert app._step() is False
    assert len(lcd.calls) == 1  # nothing new presented


def test_back_button_pops_to_root(make_app, point):
    app, lcd, touch, _clock = make_app()
    app._step()
    app.nav.push(HomeView())
    app._step()  # stack change -> re-render
    assert app._bar_hitboxes, "buttons must exist below the root"

    back_x = 0
    for (x0, _y0, x1, _y1), action in app._bar_hitboxes:
        if action == "back":
            back_x = (x0 + x1) // 2
    touch.script = [[point(back_x, 10)], []]  # down, then finger gone
    app._step()
    app._step()
    assert len(app.nav) == 1
    assert app._bar_hitboxes == []  # hidden again at root


def test_home_button_pops_to_root(make_app, point):
    app, lcd, touch, _clock = make_app()
    app._step()
    app.nav.push(HomeView())
    app.nav.push(HomeView())
    app._step()

    home_x = 0
    for (x0, _y0, x1, _y1), action in app._bar_hitboxes:
        if action == "home":
            home_x = (x0 + x1) // 2
    touch.script = [[point(home_x, 10)], []]  # down, then finger gone
    app._step()
    app._step()
    assert len(app.nav) == 1


def test_content_tap_dispatched_to_top_view(make_app, point):
    seen = []

    class Spy:
        title = "SPY"

        def render(self, draw, ctx):
            return True

        def on_tap(self, x, y, ctx):
            seen.append((x, y, ctx.content[1]))
            return True

    app, lcd, touch, _clock = make_app(touch_script=[[point(400, 300)], []])
    app.nav.push(Spy())
    app._step()  # initial render + finger down
    assert app._step() is True  # release: the tap lands on Spy
    assert seen == [(400, 300, BAR_H)]  # content starts below the bar


def test_nav_changed_flag_drives_redraw():
    nav = Nav(HomeView())
    assert nav.changed is False
    nav.push(HomeView())
    assert nav.changed is True
    nav.changed = False
    nav.pop()
    assert nav.changed is True and len(nav) == 1
    nav.changed = False
    nav.pop()  # nothing to pop
    assert nav.changed is False


def test_theme_change_in_config_retunes_live(make_app):
    app, lcd, _touch, _clock = make_app()
    present(app, lcd)
    app.config.update({"theme": "light"})
    assert app._step() is True  # full re-render on generation change
    assert app.theme.name == "light"
    assert app.canvas.getpixel((400, 5)) == app.theme.bg


def test_module_interval_render_runs_and_presents(make_app, fake_module):
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    module = fake_module("clock", interval=1)
    app.nav.push(module)
    present(app, lcd)
    clock.set(1002.0, 1_700_000_002.0)  # beyond the refresh deadline
    assert app._step() is True  # interval render returned True
    clock.set(1003.0, 1_700_000_003.0)
    assert app._step() is True  # module interval ticked again


def test_statusbar_toggle_hides_module_items(make_app, fake_module):
    from wintermode.context import BarItem

    class Chatty(fake_module):
        def status_items(self, ctx):
            return [BarItem("CHATTER")]

    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.registry._all["boston"] = Chatty("boston")
    # the bar redraws once a second — tick the wall clock to repaint it
    clock.set(1001.0, 1_700_000_001.0)
    present(app, lcd)

    def dim_pixels_in_bar():
        return any(
            app.canvas.getpixel((x, 15)) == app.theme.dim
            for x in range(0, 400)
        )

    assert dim_pixels_in_bar()  # CHATTER is shown
    app.config.update({"statusbar": {"boston": False}})
    app._step()
    assert not dim_pixels_in_bar()  # hidden by the toggle


def test_rotate_items_cycles_one_at_a_time():
    from wintermode.app import _rotate_items
    items = ["a", "b", "c"]
    assert _rotate_items(items, 0.0, 10) == ["a"]
    assert _rotate_items(items, 10.0, 10) == ["b"]
    assert _rotate_items(items, 20.0, 10) == ["c"]
    assert _rotate_items(items, 30.0, 10) == ["a"]  # wraps
    assert _rotate_items(items, 5.0, 0) == items  # rotation off
    assert _rotate_items([], 5.0, 10) == []


def test_auto_theme_flips_on_minute_boundary(make_app):
    import time as _t

    night = _t.mktime((2023, 11, 14, 23, 0, 0, 0, 0, -1))
    noon = _t.mktime((2023, 11, 14, 12, 0, 0, 0, 0, -1))
    app, lcd, _touch, clock = make_app()
    present(app, lcd)
    app.config.update({"theme": "auto",
                       "display": {"light_from": "07:00",
                                   "light_to": "19:00"}})
    clock.set(1001.0, night)
    assert app._step() is True  # generation change re-themes
    assert app.theme.name == "dark"
    # jump to noon: the minute boundary flips to light without any save
    clock.set(1002.0, noon)
    assert app._step() is True
    assert app.theme.name == "light"
    assert app.canvas.getpixel((400, 5)) == app.theme.bg


def test_config_writing_tap_retunes_in_one_frame(make_app, point):
    # a tap that saves config must produce ONE re-themed frame:
    # the form must never render under the old theme in between
    renders = []

    class ThemeTap:
        title = "TAP"

        def render(self, draw, ctx):
            renders.append(ctx.theme.name)

        def on_tap(self, x, y, ctx):
            ctx.config.update({"theme": "light"})
            return True

    app, lcd, touch, _clock = make_app(touch_script=[[point(400, 300)], []])
    app.nav.push(ThemeTap())
    app._step()  # initial render + finger down
    app._step()  # release: writes config -> one frame with light theme
    assert app.theme.name == "light"
    assert renders == ["dark", "light"]  # initial, then the themed frame


def test_wake_on_touch_sleeps_after_idle(make_app):
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.config.update({"display": {"mode": "wake_on_touch",
                                   "idle_seconds": 5}})
    clock.set(1001.0, 1_700_000_001.0)
    app._step()  # generation change: still awake
    clock.set(1010.0, 1_700_000_010.0)  # idle past 5 s
    assert app._step() is False  # the black frame was presented inside
    assert app.asleep is True
    assert lcd.sleep_calls == 1
    assert lcd.backlight_calls == [False]
    assert app.canvas.getpixel((400, 400)) == (0, 0, 0)  # black frame


def test_always_on_never_sleeps(make_app):
    app, lcd, _touch, clock = make_app()
    present(app, lcd)
    clock.set(2000.0, 1_700_001_000.0)  # hours of idle
    app._step()
    assert app.asleep is False
    assert lcd.sleep_calls == 0


def test_wake_repaints_and_swallows_the_wake_tap(make_app, point):
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.config.update({"display": {"mode": "wake_on_touch",
                                   "idle_seconds": 5}})
    clock.set(1001.0, 1_700_000_001.0)
    app._step()
    clock.set(1010.0, 1_700_000_010.0)
    app._step()  # asleep

    # the wake press is consumed by wait_touch (run()'s asleep branch)
    touch.script = [[point(400, 300)], [], []]
    assert touch.wait_touch(0.5) is True
    app._wake()
    assert app.asleep is False
    assert lcd.backlight_calls == [False, True]
    assert lcd.wake_calls == 1
    # the release afterwards fires no tap: nothing was pushed
    assert app._step() is False
    assert len(app.nav) == 1


def test_tap_activity_keeps_the_panel_awake(make_app, point):
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.config.update({"display": {"mode": "wake_on_touch",
                                   "idle_seconds": 5}})
    clock.set(1001.0, 1_700_000_001.0)
    app._step()
    # a finger down at second 1004 resets the timer
    touch.script = [[point(50, 50)], []]
    clock.set(1004.0, 1_700_000_004.0)
    app._step()
    clock.set(1008.0, 1_700_000_008.0)  # only 4 s after the touch
    app._step()
    assert app.asleep is False
    clock.set(1012.0, 1_700_000_012.0)  # 8 s after the touch
    app._step()
    assert app.asleep is True


def test_clock_module_renders_on_wall_boundaries(make_app):
    import time as _t

    from wintermode.modules.clock.module import Clock

    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.registry._all["clock"] = Clock()
    app.registry.validate_namespaces()  # fills config["clock"] defaults
    app.nav.push(app.registry["clock"])
    present(app, lcd)
    boundary = 1_700_000_001.0  # one wall second later, on the boundary
    clock.set(1002.0, boundary)
    app._step()
    expected = _t.strftime("%H:%M", _t.localtime(boundary))
    # the module refreshed AT the boundary — same second the bar shows
    assert app.registry["clock"]._last_text == expected


def test_wake_after_a_web_theme_change_repaints_in_the_new_theme(make_app):
    # the asleep branch used to consume the generation and wake with the
    # palette from before the change: the panel came up dark for up to a
    # minute after the phone switched it to light
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.config.update({"display": {"mode": "wake_on_touch",
                                   "idle_seconds": 5}})
    clock.set(1001.0, 1_700_000_001.0)
    app._step()
    clock.set(1010.0, 1_700_000_010.0)
    app._step()  # asleep

    app.config.update({"theme": "light"})  # the phone PUT lands
    app._wake()
    assert app.theme.name == "light"
    assert app.canvas.getpixel((5, 400)) == app.theme.bg


def test_actions_queued_while_asleep_run_before_the_wake(make_app):
    # run()'s asleep branch never drained the action queue, so a web
    # POST executed hours later, at the next wake
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.config.update({"display": {"mode": "wake_on_touch",
                                   "idle_seconds": 5}})
    clock.set(1001.0, 1_700_000_001.0)
    app._step()
    clock.set(1010.0, 1_700_000_010.0)
    app._step()  # asleep

    # the real boston module's abandon action, wired to its own namespace
    from wintermode.modules.boston.module import Boston

    app.registry._all["boston"] = Boston()
    assert app.registry._all["boston"].id == "boston"
    before = app.registry._all["boston"]._seq
    app.actions.put(("boston", "abandon"))
    assert app._drain_actions(1010.0, [], 1_700_000_010.0) is True
    assert app.actions.empty()
    assert app.registry._all["boston"]._seq == before + 1  # query abandoned


def test_the_waking_finger_never_fires_a_tap(make_app, point):
    # _wake() seeds the finger that is still down at wake: its release
    # must not activate whatever card it happens to land on
    app, lcd, touch, clock = make_app()
    present(app, lcd)
    app.config.update({"display": {"mode": "wake_on_touch",
                                   "idle_seconds": 5}})
    clock.set(1001.0, 1_700_000_001.0)
    app._step()
    clock.set(1010.0, 1_700_000_010.0)
    app._step()  # asleep

    touch.script = [[point(400, 400)], []]  # still down, then released
    app._wake()  # reads (and seeds) the waking finger
    assert app.tracker.update([], 1010.1) == []  # release fires nothing
    assert app._step() is False
    assert len(app.nav) == 1  # no card was activated
