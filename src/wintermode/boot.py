"""The startup splash: WINTER MODE, stepped through the crisp sizes.

The splash steps through the verified clean font sizes — smallest to
biggest, one at a time, each held for half a second — and holds the
landing.  Every frame is a static 1-bit render, so every step is crisp;
the stepping itself is the animation, and each frame costs a full-screen
blit (~0.6 s hardware-bound, faithfully replayed by the simulator).
"""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from wintermode.fonts import (
    CLEAN_SIZES,
    SIZE_BOOT_VERSION,
    Fonts,
)
from wintermode.theme import Theme

STEP_HOLD_S = 0.5
FINAL_HOLD_S = 1.2
BOOT_BASE = max(CLEAN_SIZES)  # the clean size the bigger steps scale from


def _draw_version(draw, fonts: Fonts, theme: Theme, width: int, height: int,
                  version: str) -> None:
    fonts.draw_text(
        draw,
        (width - fonts.textwidth(version, "regular", SIZE_BOOT_VERSION) - 16,
         height - 38),
        version, "regular", SIZE_BOOT_VERSION, theme.dim,
    )


def play_boot(lcd, theme: Theme, fonts: Fonts, version: str) -> None:
    """Step WINTER MODE up the clean-size ladder, then hold the landing."""
    width, height = lcd.width, lcd.height
    canvas = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(canvas)

    # the landing size: the largest integer multiple of the clean size
    # that still fits inside the frame (advance widths scale linearly)
    base_w = fonts.textwidth("WINTER MODE", "regular", BOOT_BASE)
    multiple = max(1, (width - 40) // base_w)
    steps = [min(CLEAN_SIZES)] + [BOOT_BASE * k for k in range(1, multiple + 1)]

    for size in steps:
        draw.rectangle((0, 0, width, height), fill=theme.bg)
        x = (width - fonts.textwidth("WINTER MODE", "regular", size)) / 2
        y = (height - fonts.textsize("WINTER MODE", "regular", size)[1]) / 2
        fonts.draw_text(draw, (x, y), "WINTER MODE", "regular", size,
                        theme.fg)
        _draw_version(draw, fonts, theme, width, height, version)
        lcd.image(canvas)
        time.sleep(STEP_HOLD_S if size != steps[-1] else FINAL_HOLD_S)
