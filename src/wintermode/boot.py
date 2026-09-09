"""The startup splash: WINTER MODE, slow zoom.

This is the ONLY animation in the app, deliberately: every zoom frame
changes nearly every pixel, so driver diffing cannot help and each frame
costs a full-screen blit (~0.6 s hardware-bound, faithfully replayed by
the simulator).  14 frames ≈ 8.5 s is the stately pace.  Never reuse
this pattern in the UI.
"""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from wintermode.fonts import Fonts
from wintermode.theme import Theme

FRAMES = 14
MAX_SIZE = 150  # px cap; the actual ceiling is "fits inside the frame"


def _font_size(frame: int, fonts: Fonts, width: int) -> int:
    """Ease-in-out zoom, ending at the largest size that still fits.

    Advance widths scale linearly with the point size, so one
    measurement at 100 px gives the exact fit ceiling.
    """
    start = 24
    fit = int(100 * (width - 40) / fonts.textwidth("WINTER MODE", "regular", 100))
    ceiling = min(MAX_SIZE, fit)
    t = frame / (FRAMES - 1)
    eased = t * t * (3 - 2 * t)  # smoothstep: slow, fast, slow
    return int(start + eased * (ceiling - start))


def play_boot(lcd, theme: Theme, fonts: Fonts, version: str) -> None:
    """Zoom WINTER MODE in slowly, staying inside the frame, then hold."""
    width, height = lcd.width, lcd.height
    canvas = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(canvas)

    for frame in range(FRAMES):
        draw.rectangle((0, 0, width, height), fill=theme.bg)
        font = fonts.get("regular", _font_size(frame, fonts, width))
        x = (width - fonts.textwidth("WINTER MODE", "regular", font.size)) / 2
        y = (height - fonts.textsize("WINTER MODE", "regular", font.size)[1]) / 2
        draw.text((x, y), "WINTER MODE", font=font, fill=theme.fg)

        small = fonts.get("regular", 22)
        draw.text(
            (width - fonts.textwidth(version, "regular", 22) - 16, height - 38),
            version,
            font=small,
            fill=theme.dim,
        )
        lcd.image(canvas)

    time.sleep(1.2)  # hold the final frame before the cut to home
