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
