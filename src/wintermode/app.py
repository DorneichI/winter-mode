"""winter-mode application — boot, main loop, view stack.

The app only ever touches hardware through the injected `lcd` and `touch`
seams, so everything here is testable with fakes and runs unchanged in
the simulator (`ERTFTM070_DISPLAY=sim`).
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from ertftm070 import Display, Touch
from PIL import Image, ImageDraw

from wintermode import __version__
from wintermode.boot import play_boot
from wintermode.fonts import Fonts
from wintermode.theme import Theme, resolve

log = logging.getLogger(__name__)

BAR_H = 28  # persistent top bar height


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

    def __init__(self, lcd, touch, theme: Theme, fonts: Fonts) -> None:
        self.lcd = lcd
        self.touch = touch
        self.theme = theme
        self.fonts = fonts
        self.canvas = Image.new("RGB", (lcd.width, lcd.height), theme.bg)
        self.draw = ImageDraw.Draw(self.canvas)

    # --- bar -------------------------------------------------------------

    def _draw_bar(self) -> None:
        draw = self.draw
        theme = self.theme
        draw.rectangle((0, 0, self.lcd.width, BAR_H), fill=theme.bg)
        draw.line(
            (0, BAR_H - 1, self.lcd.width - 1, BAR_H - 1), fill=theme.border
        )
        clock = time.strftime("%H:%M:%S")
        draw.text((8, 4), clock, font=self.fonts.get("regular", 18), fill=theme.fg)

    # --- lifecycle --------------------------------------------------------

    def run(self) -> None:
        self._draw_bar()
        self.lcd.image(self.canvas)
        log.info("running (bar + clock) — Ctrl-C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass  # the Display context manager turns the backlight off


def main() -> None:
    _parse_args()  # --config is wired up when the config layer lands
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    # Touch must close before Display (the bus is single-owner), so Touch
    # is opened first in the with-statement.
    with Display() as lcd, Touch(lcd.bus) as touch:
        # config.json lands in a later step; dark is the default for now
        theme = resolve("dark")
        fonts = Fonts()
        play_boot(lcd, theme, fonts, __version__)
        WinterApp(lcd, touch, theme, fonts).run()


if __name__ == "__main__":
    main()
