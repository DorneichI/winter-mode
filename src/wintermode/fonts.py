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
    # masks are what every label on the panel is pasted from; a frame
    # redraws the same strings over and over, so cache them.  Cleared
    # wholesale when full — bounded, and no LRU bookkeeping per frame.
    MASK_CACHE_MAX = 512

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or FONTS_DIR
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._masks: dict[tuple[str, str, int], Image.Image] = {}

    def get(self, weight: str, size: int) -> ImageFont.FreeTypeFont:
        key = (weight, size)
        font = self._cache.get(key)
        if font is None:
            font = ImageFont.truetype(str(self._dir / WEIGHTS[weight]), size)
            self._cache[key] = font
        return font

    def textwidth(self, text: str, weight: str, size: int) -> int:
        """Advance width — the space the text takes in a line of text."""
        return int(round(self.get(weight, size).getlength(text)))

    def textsize(self, text: str, weight: str, size: int) -> tuple[int, int]:
        """(advance width, INK height) of `text`.

        Height is the ink the glyphs actually put down, not the font's
        layout box.  `getbbox()` reports the ascender/descender band:
        for '-' that is 10 rows of which exactly one has ink, so
        centring on it left the dash near the top of its button.
        """
        return self.textwidth(text, weight, size), self._ink_box(
            text, weight, size)[3]

    def center_y(self, text: str, weight: str, size: int, y0: float,
                 y1: float) -> float:
        """The `draw_text` y that centers `text`'s INK in the band y0..y1.

        The one vertical-centering rule in the app: a value, a label and
        a `-`/`+` glyph all land on the same optical middle, whatever
        their ink height.
        """
        top, _bottom, height = self._ink_box(text, weight, size)
        return y0 + (y1 - y0 - height) / 2 - top

    # --- the one text path --------------------------------------------------

    def _ink_box(self, text: str, weight: str, size: int) -> tuple[int, int, int]:
        """(top, bottom, height) of the rendered ink within the mask."""
        box = self._bilevel_mask(text, weight, size).getbbox()
        if box is None:  # nothing drawn (empty or all-blank text)
            return 0, 0, 0
        return box[1], box[3], box[3] - box[1]

    def _bilevel_mask(self, text: str, weight: str, size: int) -> Image.Image:
        key = (text, weight, size)
        mask = self._masks.get(key)
        if mask is None:
            font = self.get(weight, size)
            left, top, right, bottom = font.getbbox(text)
            mask = Image.new("1", (max(1, right - left), max(1, bottom - top)), 0)
            ImageDraw.Draw(mask).text((-left, -top), text, font=font, fill=1)
            if len(self._masks) >= self.MASK_CACHE_MAX:
                self._masks.clear()
            self._masks[key] = mask
        return mask

    def draw_text(self, draw, xy, text: str, weight: str, size: int, fill) -> None:
        """Bilevel text at (x, y).  Every call site in the app goes here."""
        if not text:
            return
        # rasterize ONCE, at the size that will actually be pasted: the
        # nearest-clean size when the request is not already clean
        clean = size if size in CLEAN_SIZES else min(
            CLEAN_SIZES, key=lambda s: abs(s - size)
        )
        mask = self._bilevel_mask(text, weight, clean)
        if clean != size:
            scale = size / clean
            mask = mask.resize(
                (max(1, round(mask.width * scale)),
                 max(1, round(mask.height * scale))),
                Image.NEAREST,
            )
        # round, not truncate: callers hand in measured float centers
        draw.bitmap((round(xy[0]), round(xy[1])), mask, fill=fill)
