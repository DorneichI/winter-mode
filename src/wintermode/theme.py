"""Design tokens for the terminal look.

Every pixel the app draws comes from a Theme — modules never hardcode
colors.  Selection/pressed state is inverse video (fg text on bg).  Night
is a palette only: the driver's backlight is on/off, so dimming is a
future concern, not a theme concern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Theme:
    name: str
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]
    accent: tuple[int, int, int]
    dim: tuple[int, int, int]
    border: tuple[int, int, int]


THEMES: dict[str, Theme] = {
    "dark": Theme(
        "dark",
        bg=(0, 0, 0),
        fg=(232, 232, 232),
        accent=(80, 220, 140),
        dim=(110, 110, 110),
        border=(95, 95, 95),
    ),
    "light": Theme(
        "light",
        bg=(244, 242, 238),
        fg=(28, 28, 28),
        accent=(0, 130, 75),
        dim=(135, 130, 125),
        border=(180, 175, 170),
    ),
    # dim amber phosphor on near-black — a palette, not a backlight setting
    "night": Theme(
        "night",
        bg=(10, 8, 3),
        fg=(205, 165, 65),
        accent=(150, 110, 30),
        dim=(110, 88, 34),
        border=(70, 56, 22),
    ),
}


def resolve(name: str) -> Theme:
    theme = THEMES.get(name)
    if theme is None:
        log.warning("unknown theme %r, falling back to dark", name)
        theme = THEMES["dark"]
    return theme
