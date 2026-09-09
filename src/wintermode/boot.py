"""The startup splash: WINTER MODE, slow zoom, crisp landing.

This is the ONLY animation in the app, deliberately: every zoom frame
changes nearly every pixel, so driver diffing cannot help and each frame
costs a full-screen blit (~0.6 s hardware-bound, faithfully replayed by
the simulator).  The moving frames are exempt from the 1-bit text rule
(anti-aliasing keeps the motion smooth); the final frame locks in crisp
— rendered through Fonts.draw_text at an integer multiple of the
verified 44 px clean size, so the pixel grid lands perfectly.
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

FRAMES = 14
START_SIZE = 24
BOOT_BASE = max(CLEAN_SIZES)  # the clean size the landing frame scales from


def _draw_version(draw, fonts: Fonts, theme: Theme, width: int, height: int,
                  version: str) -> None:
    fonts.draw_text(
        draw,
        (width - fonts.textwidth(version, "regular", SIZE_BOOT_VERSION) - 16,
         height - 38),
        version, "regular", SIZE_BOOT_VERSION, theme.dim,
    )


def play_boot(lcd, theme: Theme, fonts: Fonts, version: str) -> None:
    """Zoom WINTER MODE in slowly, staying inside the frame, then hold."""
    width, height = lcd.width, lcd.height
    canvas = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(canvas)

    # the landing size: the largest integer multiple of the clean size
    # that still fits inside the frame (advance widths scale linearly)
    base_w = fonts.textwidth("WINTER MODE", "regular", BOOT_BASE)
    multiple = max(1, (width - 40) // base_w)
    final_size = BOOT_BASE * multiple

    for frame in range(FRAMES - 1):  # moving frames: AA, exempt from 1-bit
        draw.rectangle((0, 0, width, height), fill=theme.bg)
        t = frame / (FRAMES - 2)
        eased = t * t * (3 - 2 * t)  # smoothstep: slow, fast, slow
        size = int(START_SIZE + eased * (final_size - START_SIZE))
        font = fonts.get("regular", size)
        x = (width - fonts.textwidth("WINTER MODE", "regular", size)) / 2
        y = (height - fonts.textsize("WINTER MODE", "regular", size)[1]) / 2
        draw.text((x, y), "WINTER MODE", font=font, fill=theme.fg)
        _draw_version(draw, fonts, theme, width, height, version)
        lcd.image(canvas)

    # final frame + hold: crisp 1-bit landing at the fit size
    draw.rectangle((0, 0, width, height), fill=theme.bg)
    x = (width - fonts.textwidth("WINTER MODE", "regular", final_size)) / 2
    y = (height - fonts.textsize("WINTER MODE", "regular", final_size)[1]) / 2
    fonts.draw_text(draw, (x, y), "WINTER MODE", "regular", final_size,
                    theme.fg)
    _draw_version(draw, fonts, theme, width, height, version)
    lcd.image(canvas)

    time.sleep(1.2)  # hold the final frame before the cut to home
