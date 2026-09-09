"""The startup splash: WINTER MODE, slow ease-out zoom.

This is the ONLY animation in the app, deliberately: every zoom frame
changes nearly every pixel, so driver diffing cannot help and each frame
costs a full-screen blit (~0.6 s hardware-bound, faithfully replayed by
the simulator).  ~8 eased frames ≈ 5 s is the stately pace.  Never reuse
this pattern in the UI.
"""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from wintermode.fonts import Fonts
from wintermode.theme import Theme

FRAMES = 8


def _font_size(frame: int) -> int:
    # ease-out: grows fast early, slow late — the cinematic zoom.
    eased = 1 - (1 - frame / (FRAMES - 1)) ** 2
    return int(24 + eased * 116)  # 24 px → 140 px, wide enough to clip


def play_boot(lcd, theme: Theme, fonts: Fonts, version: str) -> None:
    """Zoom WINTER MODE in from tiny to clipped-large, then hold."""
    width, height = lcd.width, lcd.height
    canvas = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(canvas)

    for frame in range(FRAMES):
        draw.rectangle((0, 0, width, height), fill=theme.bg)
        font = fonts.get("regular", _font_size(frame))
        # centered on the text's advance width so the zoom feels stable
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

    time.sleep(0.8)  # hold the final frame before the cut to home
