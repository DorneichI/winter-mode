"""winter-mode application — boot, main loop, view stack.

The app only ever touches hardware through the injected `lcd` and `touch`
seams, so everything here is testable with fakes and runs unchanged in
the simulator (`ERTFTM070_DISPLAY=sim`).

Threading rule: only the main loop thread ever draws or blits.  Any
background threads fetch/parse data only.
"""

from __future__ import annotations

import argparse
import logging
import queue
import time
from collections.abc import Callable
from pathlib import Path

from ertftm070 import Display, Touch
from PIL import Image, ImageDraw

from wintermode import __version__
from wintermode.boot import play_boot
from wintermode.config import Config
from wintermode.context import Ctx, Nav
from wintermode.fonts import SIZE_BAR, Fonts
from wintermode.registry import Registry, discover
from wintermode.taps import TapTracker
from wintermode.theme import Theme, effective_theme
from wintermode.views import HomeView

log = logging.getLogger(__name__)

BAR_H = 30  # persistent top bar height


def _rotate_items(items: list, wall: float, rotate_seconds: int) -> list:
    """Status-bar rotation: one item at a time; 0 disables rotation."""
    if not items or rotate_seconds <= 0:
        return items
    index = int(wall) // max(1, rotate_seconds) % len(items)
    return [items[index]]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wintermode", description="winter-mode kitchen dashboard"
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="path to config.json"
    )
    parser.add_argument(
        "--web-port", type=int, default=None,
        help="web UI port (default 8080, 0 for an ephemeral port)",
    )
    return parser.parse_args(argv)


class WinterApp:
    """Owns the framebuffer canvas and drives it; views draw via Ctx."""

    def __init__(
        self,
        lcd,
        touch,
        theme: Theme,
        fonts: Fonts,
        clock: Callable[[], tuple[float, float]] | None = None,
        config=None,
        registry=None,
    ) -> None:
        self.lcd = lcd
        self.touch = touch
        self.theme = theme
        self.fonts = fonts
        self.config = config
        self.registry = registry
        # clock() -> (monotonic, wall); injectable so tests control time
        self.clock = clock or (lambda: (time.monotonic(), time.time()))
        self.canvas = Image.new("RGB", (lcd.width, lcd.height), theme.bg)
        self.draw = ImageDraw.Draw(self.canvas)
        self.nav = Nav(HomeView(registry=registry, config=config))
        self.nav.changed = True  # the first loop pass paints the initial frame
        self.tracker = TapTracker()
        self.last_second: int | None = None
        self.last_minute: int | None = None
        self.last_gen = config.generation if config else 0
        self._next_refresh = 0.0
        self.asleep = False
        self.last_touch = self.clock()[0]  # the sleep timer starts at boot
        self.actions: queue.Queue = queue.Queue()  # web POSTs land here
        self.web_port: int | None = None  # set once the web server binds
        self._bar_hitboxes: list[tuple[tuple[int, int, int, int], str]] = []

    # --- context ----------------------------------------------------------

    def _ctx(self, now: float, points, wall: float) -> Ctx:
        return Ctx(
            theme=self.theme,
            fonts=self.fonts,
            nav=self.nav,
            content=(0, BAR_H, self.lcd.width, self.lcd.height),
            width=self.lcd.width,
            height=self.lcd.height,
            points=points,
            now=now,
            wall=wall,
            config=self.config,
            registry=self.registry,
            web_port=self.web_port,
        )

    # --- bar --------------------------------------------------------------

    def _draw_bar(self, now: float, points, wall: float) -> None:
        draw = self.draw
        theme = self.theme
        width = self.lcd.width
        draw.rectangle((0, 0, width, BAR_H), fill=theme.bg)
        draw.line((0, BAR_H - 1, width - 1, BAR_H - 1), fill=theme.border)

        clock_text = time.strftime("%H:%M:%S", time.localtime(wall))
        self.fonts.draw_text(draw, (8, 5), clock_text, "regular", SIZE_BAR,
                             theme.fg)

        # status items published by enabled modules (rotating), up to
        # the title zone
        x = 8 + self.fonts.textwidth(clock_text, "regular", SIZE_BAR) + 16
        if self.registry and self.config:
            ctx = self._ctx(now, points, wall)
            items = []
            for module in self.registry.home_order():
                if not self.config.data["statusbar"].get(module.id, True):
                    continue
                items.extend(module.status_items(ctx))
            rotate = self.config.data.get("statusbar_rotate", 0)
            for item in _rotate_items(items, wall, rotate):
                label = f"[{item.text}]"
                label_w = self.fonts.textwidth(label, "regular", SIZE_BAR)
                if x + label_w > width // 2 - 80:
                    break  # the bar is full; the title zone is sacred
                self.fonts.draw_text(draw, (x, 5), label, "regular",
                                     SIZE_BAR, theme.dim)
                x += label_w + 12

        title = getattr(self.nav.top, "title", "HOME")
        self.fonts.draw_text(
            draw,
            ((width - self.fonts.textwidth(title, "regular", SIZE_BAR)) / 2, 5),
            title, "regular", SIZE_BAR, theme.fg,
        )

        self._bar_hitboxes = []
        if len(self.nav) > 1:  # back/home exist only below the root
            home = "[⌂ HOME]"
            home_w = self.fonts.textwidth(home, "regular", SIZE_BAR)
            home_x = width - home_w - 8
            self.fonts.draw_text(draw, (home_x, 5), home, "regular",
                                 SIZE_BAR, theme.accent)
            self._bar_hitboxes.append(((home_x, 0, width, BAR_H), "home"))

            back = "[‹ BACK]"
            back_w = self.fonts.textwidth(back, "regular", SIZE_BAR)
            back_x = home_x - back_w - 10
            self.fonts.draw_text(draw, (back_x, 5), back, "regular",
                                 SIZE_BAR, theme.accent)
            self._bar_hitboxes.append(((back_x, 0, home_x, BAR_H), "back"))

    def _bar_tap(self, x: int) -> bool:
        for (x0, _y0, x1, _y1), action in self._bar_hitboxes:
            if x0 <= x < x1:
                if action == "back":
                    self.nav.pop()
                else:
                    self.nav.home()
                return True
        return False

    # --- main loop ---------------------------------------------------------

    def _render_content(self, now: float, points, wall: float) -> None:
        self.nav.top.render(self.draw, self._ctx(now, points, wall))

    def _repaint(self, now: float, points, wall: float) -> None:
        """One full-frame repaint: clear, re-render the content, redraw the bar.

        The single place the whole canvas is rebuilt, so a theme change,
        a nav change, a minute flip and a wake can never drift apart.
        """
        self.draw.rectangle((0, 0, self.lcd.width, self.lcd.height),
                            fill=self.theme.bg)
        self._render_content(now, points, wall)
        self._draw_bar(now, points, wall)

    def _reload_theme(self, wall: float) -> bool:
        """Pick up a theme change from config; True when it actually moved."""
        theme = effective_theme(self.config, wall)
        if theme == self.theme:
            return False
        self.theme = theme
        return True

    def _drain_actions(self, now: float, points, wall: float) -> bool:
        """Run every web-queued (module_id, action_id) on this thread.

        True when at least one ran.  Called from the sleeping branch too:
        an action POSTed while the panel sleeps must run now, not hours
        later on the way back up.
        """
        ran = False
        while not self.actions.empty():
            module_id, action_id = self.actions.get_nowait()
            module = self.registry.get(module_id) if self.registry else None
            if module is not None:
                try:
                    module.on_action(action_id, self._ctx(now, points, wall))
                except Exception:  # one bad action must not kill the loop
                    log.exception("module %s action %r failed", module_id,
                                  action_id)
            ran = True
        return ran

    def _step(self) -> bool:
        """One loop pass.  Returns True when the canvas changed."""
        now, wall = self.clock()
        points = self.touch.read(mapped=True)
        dirty = False
        rerender_content = False

        # web-triggered actions execute here, on the main loop thread
        if self._drain_actions(now, points, wall):
            rerender_content = True
            dirty = True

        events = self.tracker.update(points, now)
        if points:  # any finger activity resets the sleep timer
            self.last_touch = now
        for kind, x, y in events:
            if y < BAR_H:
                if kind == "tap":
                    dirty |= self._bar_tap(x)
                continue
            if kind == "tap":
                if self.nav.top.on_tap(x, y, self._ctx(now, points, wall)):
                    # a consumed tap may have changed view state (page
                    # flip, form value) — re-render the content area.
                    # Deferred: if the tap also saved config, the
                    # generation watcher below re-themes AND re-renders
                    # in ONE frame instead of two.
                    rerender_content = True
                    dirty = True

        if self.nav.changed:
            self.nav.changed = False
            # align refreshes to wall-clock second boundaries so module
            # updates and the bar tick land in the same frame
            self._next_refresh = int(wall) + 1
            self._repaint(now, points, wall)
            dirty = True
            rerender_content = False

        # live config reload AFTER touch processing: a config-writing
        # tap lands as a single re-themed frame, not form-then-theme
        if self.config and self.config.generation != self.last_gen:
            self.last_gen = self.config.generation
            self._reload_theme(wall)
            self._repaint(now, points, wall)
            return True

        if rerender_content:
            self._render_content(now, points, wall)

        # module refresh interval, wall-aligned: the clock's once-a-
        # second render lands on the same boundary as the bar's tick
        top = self.nav.top
        if getattr(top, "interval", 0) and int(wall) >= self._next_refresh:
            self._next_refresh = int(wall) + top.interval
            if top.render(self.draw, self._ctx(now, points, wall)):
                dirty = True

        if self.last_second != int(wall):
            self.last_second = int(wall)
            self._draw_bar(now, points, wall)
            dirty = True

        # the auto theme schedule flips light/dark on minute boundaries
        minute = int(wall) // 60
        if self.last_minute != minute:
            self.last_minute = minute
            if self.config and self._reload_theme(wall):
                self._repaint(now, points, wall)
                dirty = True

        # wake_on_touch: idle long enough -> black frame, panel sleeps
        if self.config and not self.asleep:
            display = self.config.data.get("display", {})
            if display.get("mode") == "wake_on_touch" and (
                now - self.last_touch > display.get("idle_seconds", 60)
            ):
                self._enter_sleep()  # presents the black frame itself
                return False  # run() must not present again

        return dirty

    # --- sleep / wake -------------------------------------------------------

    def _enter_sleep(self) -> None:
        # fill black BEFORE sleep() — the panel's center-fade artifact
        self.draw.rectangle((0, 0, self.lcd.width, self.lcd.height),
                            fill=(0, 0, 0))
        self.lcd.image(self.canvas)
        self.lcd.sleep()
        self.lcd.backlight(False)
        self.asleep = True
        log.info("asleep — any touch wakes (display mode: wake_on_touch)")

    def _wake(self) -> None:
        self.lcd.backlight(True)
        self.lcd.wake()
        self.asleep = False
        now, wall = self.clock()
        self.last_touch = now
        points = self.touch.read(mapped=True)
        # the waking tap must never activate UI: seed it as dead
        self.tracker.seed(points, now)
        # a config change that landed while asleep must be on screen the
        # instant the panel comes back — repaint with the CURRENT theme
        if self.config:
            self._reload_theme(wall)
        self._repaint(now, points, wall)
        self.lcd.image(self.canvas)
        log.info("woke up")

    def run(self) -> None:
        log.info("running — Ctrl-C to stop")
        try:
            while True:
                if self.asleep:
                    # actions and config changes queued while asleep
                    # (web POST/PUT) land before the panel comes back
                    now, wall = self.clock()
                    if self._drain_actions(now, [], wall):
                        self._wake()
                        continue
                    # a config change while asleep (e.g. web PUT) wakes too
                    if self.config and self.config.generation != self.last_gen:
                        self.last_gen = self.config.generation
                        self._wake()
                        continue
                    if self.touch.wait_touch(timeout=0.5):
                        self._wake()
                    continue
                if self._step():
                    self.lcd.image(self.canvas)
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass  # the Display context manager turns the backlight off


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    config = Config(args.config or Path("config.json"))
    registry = Registry(discover(), config)
    registry.validate_namespaces()
    # Touch must close before Display (the bus is single-owner), so Touch
    # is opened first in the with-statement.
    with Display() as lcd, Touch(lcd.bus) as touch:
        theme = effective_theme(config, time.time())
        fonts = Fonts()
        app = WinterApp(lcd, touch, theme, fonts, config=config,
                        registry=registry)
        # the web companion starts before the loop so it is up by boot-end
        from wintermode.web.server import DEFAULT_PORT, WebServer

        port = DEFAULT_PORT if args.web_port is None else args.web_port
        server = WebServer(config, registry, app.actions, port=port)
        server.start()
        # whatever port the kernel actually gave us (0 = ephemeral)
        app.web_port = server.port
        play_boot(lcd, theme, fonts, __version__)
        app.run()


if __name__ == "__main__":
    main()
