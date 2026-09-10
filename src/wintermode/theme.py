"""Design tokens for the terminal look, plus the auto theme schedule.

Every pixel the app draws comes from a Theme — modules never hardcode
colors.  Selection/pressed state is inverse video (fg text on bg).
`theme: auto` switches light/dark on the display.light_from/light_to
schedule; the app re-checks once a minute.
"""

from __future__ import annotations

import logging
import time
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
}


def resolve(name: str) -> Theme:
    theme = THEMES.get(name)
    if theme is None:
        log.warning("unknown theme %r, falling back to dark", name)
        theme = THEMES["dark"]
    return theme


def _in_light_window(now: str, light_from: str, light_to: str) -> bool:
    if light_from <= light_to:
        return light_from <= now < light_to
    return now >= light_from or now < light_to  # window crosses midnight


def effective_theme(config, wall: float) -> Theme:
    """The theme for this wall-clock second, honoring `theme: auto`."""
    if config is None:
        return THEMES["dark"]
    name = config.data.get("theme", "dark")
    if name != "auto":
        return resolve(name)
    now = time.strftime("%H:%M", time.localtime(wall))
    display = config.data.get("display", {})
    if _in_light_window(now, display.get("light_from", "07:00"),
                        display.get("light_to", "19:00")):
        return THEMES["light"]
    return THEMES["dark"]
