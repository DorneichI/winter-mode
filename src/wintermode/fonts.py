"""Lazy font cache around the bundled IBM 3270 faces.

ImageFont.truetype parses the whole font per (weight, size) — on a Pi
Zero that is a real one-time stall — so every face/size combination is
loaded once and cached.  Never call truetype per frame.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

FONTS_DIR = Path(__file__).parent / "fonts"

# 3270 has no bold; SemiCondensed serves as the emphasis face.
WEIGHTS = {
    "regular": "3270-Regular.ttf",
    "bold": "3270SemiCondensed-Regular.ttf",
}


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
