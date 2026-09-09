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
import time
from collections.abc import Callable
from pathlib import Path

from ertftm070 import Display, Touch
from PIL import Image, ImageDraw

from wintermode import __version__
from wintermode.boot import play_boot
from wintermode.config import Config
from wintermode.context import Ctx, Nav
from wintermode.fonts import Fonts
from wintermode.registry import Registry, discover
from wintermode.taps import TapTracker
from wintermode.theme import Theme, resolve
from wintermode.views import HomeView

log = logging.getLogger(__name__)

BAR_H = 28  # persistent top bar height
BAR_FONT = 18


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wintermode", description="winter-mode kitchen dashboard"
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="path to config.json"
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
        self.tracker = TapTracker()
        self.last_second: int | None = None
        self._bar_hitboxes: list[tuple[tuple[int, int, int, int], str]] = []

    # --- context ----------------------------------------------------------

    def _ctx(self, now: float, points) -> Ctx:
        return Ctx(
            theme=self.theme,
            fonts=self.fonts,
            nav=self.nav,
            content=(0, BAR_H, self.lcd.width, self.lcd.height),
            width=self.lcd.width,
            height=self.lcd.height,
            points=points,
            now=now,
            config=self.config,
            registry=self.registry,
        )

    # --- bar --------------------------------------------------------------

    def _draw_bar(self, wall: float) -> None:
        draw = self.draw
        theme = self.theme
        width = self.lcd.width
        draw.rectangle((0, 0, width, BAR_H), fill=theme.bg)
        draw.line((0, BAR_H - 1, width - 1, BAR_H - 1), fill=theme.border)

        clock_text = time.strftime("%H:%M:%S", time.localtime(wall))
        draw.text(
            (8, 4), clock_text, font=self.fonts.get("regular", BAR_FONT),
            fill=theme.fg,
        )

        title = getattr(self.nav.top, "title", "HOME")
        draw.text(
            ((width - self.fonts.textwidth(title, "regular", BAR_FONT)) / 2, 4),
            title, font=self.fonts.get("regular", BAR_FONT), fill=theme.fg,
        )

        self._bar_hitboxes = []
        if len(self.nav) > 1:  # back/home exist only below the root
            home = "[⌂ HOME]"
            home_w = self.fonts.textwidth(home, "regular", BAR_FONT)
            home_x = width - home_w - 8
            draw.text(
                (home_x, 4), home, font=self.fonts.get("regular", BAR_FONT),
                fill=theme.accent,
            )
            self._bar_hitboxes.append(((home_x, 0, width, BAR_H), "home"))

            back = "[‹ BACK]"
            back_w = self.fonts.textwidth(back, "regular", BAR_FONT)
            back_x = home_x - back_w - 10
            draw.text(
                (back_x, 4), back, font=self.fonts.get("regular", BAR_FONT),
                fill=theme.accent,
            )
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

    def _render_content(self, now: float, points) -> None:
        self.nav.top.render(self.draw, self._ctx(now, points))

    def _step(self) -> bool:
        """One loop pass.  Returns True when the canvas changed."""
        now, wall = self.clock()
        points = self.touch.read(mapped=True)
        dirty = False

        events = self.tracker.update(points, now)
        for kind, x, y in events:
            if y < BAR_H:
                if kind == "tap":
                    dirty |= self._bar_tap(x)
                continue
            if kind == "tap":
                if self.nav.top.on_tap(x, y, self._ctx(now, points)):
                    # a consumed tap may have changed view state (page
                    # flip, form value) — re-render the content area
                    self._render_content(now, points)
                    dirty = True

        if self.nav.changed:
            self.nav.changed = False
            self._render_content(now, points)
            self._draw_bar(wall)
            dirty = True

        if self.last_second != int(wall):
            self.last_second = int(wall)
            self._draw_bar(wall)
            dirty = True

        return dirty

    def run(self) -> None:
        log.info("running — Ctrl-C to stop")
        try:
            while True:
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
        theme = resolve(config.data["theme"])
        fonts = Fonts()
        play_boot(lcd, theme, fonts, __version__)
        WinterApp(lcd, touch, theme, fonts, config=config, registry=registry).run()


if __name__ == "__main__":
    main()
