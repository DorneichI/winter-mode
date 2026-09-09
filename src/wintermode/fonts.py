"""Lazy font cache + the ONE text-drawing path the whole app uses.

IBM 3270 is a bitmap-derived face: it is meant to render hard on/off,
never anti-aliased.  `Fonts.draw_text` rasterizes into a bilevel mask
(mode "1", thresholded by the draw into it) and pastes with
`draw.bitmap()` — every pixel fully on or off, no grays, integer
coordinates.  It is also faster than AA rendering, which the Pi Zero
appreciates.

Sizes: stem widths quantize to whole pixels in this face.  The verified
crisp set is 26 (uniform 2 px stems) and 44 (uniform 3 px stems) —
named constants below.  Any other requested size renders at the nearest
clean size and the bilevel mask is nearest-neighbor scaled, so pixels
stay square and hard-edged.

ImageFont.truetype parses the whole font per (weight, size) — on a Pi
Zero that is a real one-time stall — so every face/size combination is
loaded once and cached.  Never call truetype per frame.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = Path(__file__).parent / "fonts"

# 3270 has no bold; SemiCondensed serves as the emphasis face.
WEIGHTS = {
    "regular": "3270-Regular.ttf",
    "bold": "3270SemiCondensed-Regular.ttf",
}

# Verified crisp sizes (uniform stem widths — see module docstring).
SIZE_BAR = 26
SIZE_CARD = 26
SIZE_FORM = 26
SIZE_PAGINATOR = 26
SIZE_CLOCK = 44
SIZE_BOOT_VERSION = 26
CLEAN_SIZES = (26, 44)


class Fonts:
    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or FONTS_DIR
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def get(self, weight: str, size: int) -> ImageFont.FreeTypeFont:
        key = (weight, size)
        font = self._cache.get(key)
        if font is None:
            font = ImageFont.truetype(str(self._dir / WEIGHTS[weight]), size)
            self._cache[key] = font
        return font

    def textwidth(self, text: str, weight: str, size: int) -> int:
        return int(round(self.get(weight, size).getlength(text)))

    def textsize(self, text: str, weight: str, size: int) -> tuple[int, int]:
        """(width, height) of `text` — height is the rendered bbox height."""
        font = self.get(weight, size)
        left, top, right, bottom = font.getbbox(text)
        return right - left, bottom - top

    # --- the one text path --------------------------------------------------

    def _bilevel_mask(self, text: str, weight: str, size: int) -> Image.Image:
        font = self.get(weight, size)
        left, top, right, bottom = font.getbbox(text)
        mask = Image.new("1", (right - left, bottom - top), 0)
        ImageDraw.Draw(mask).text((-left, -top), text, font=font, fill=1)
        return mask

    def draw_text(self, draw, xy, text: str, weight: str, size: int, fill) -> None:
        """Bilevel text at (x, y).  Every call site in the app goes here."""
        if not text:
            return
        mask = self._bilevel_mask(text, weight, size)
        if size not in CLEAN_SIZES:
            clean = min(CLEAN_SIZES, key=lambda s: abs(s - size))
            if clean != size:
                scale = size / clean
                mask = self._bilevel_mask(text, weight, clean)
                mask = mask.resize(
                    (max(1, round(mask.width * scale)),
                     max(1, round(mask.height * scale))),
                    Image.NEAREST,
                )
        draw.bitmap((int(xy[0]), int(xy[1])), mask, fill=fill)
