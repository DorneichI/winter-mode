"""Shared test fixtures for winter-mode.

The app only ever touches hardware through the injected `lcd` and `touch`
seams, so tests substitute fakes here — same philosophy as the ert
driver's FakeBus. Nothing in this file needs a Raspberry Pi.
"""

from __future__ import annotations

import pytest
from ertftm070.touch import EVENT_DOWN, TouchPoint
from PIL import Image

from wintermode.app import WinterApp
from wintermode.fonts import Fonts
from wintermode.theme import resolve


class FakeLCD:
    """Duck-types the Display surface the app uses; records blits."""

    width = 800
    height = 480

    def __init__(self) -> None:
        self.calls: list[Image.Image] = []

    def image(self, img: Image.Image, x: int = 0, y: int = 0, **kw) -> None:
        self.calls.append(img.copy())


class ScriptedTouch:
    """read() returns scripted point-lists per call, then empty."""

    def __init__(self, script: list[list[TouchPoint]]) -> None:
        self.script = list(script)
        self.i = 0

    def read(self, mapped: bool = True) -> list[TouchPoint]:
        if self.i >= len(self.script):
            return []
        points = self.script[self.i]
        self.i += 1
        return points


class FakeClock:
    """Advance mono/wall explicitly: `clock.set(mono, wall)`."""

    def __init__(self, mono: float = 1000.0, wall: float = 1_700_000_000.0) -> None:
        self.mono = mono
        self.wall = wall

    def set(self, mono: float, wall: float) -> None:
        self.mono = mono
        self.wall = wall

    def __call__(self) -> tuple[float, float]:
        return self.mono, self.wall


@pytest.fixture
def point():
    """TouchPoint factory; the panel reports CONTACT after DOWN."""

    def _point(x: int, y: int, fid: int = 0, event: int = EVENT_DOWN) -> TouchPoint:
        return TouchPoint(x=x, y=y, id=fid, event=event)

    return _point


@pytest.fixture
def fonts() -> Fonts:
    return Fonts()


@pytest.fixture
def theme():
    return resolve("dark")


@pytest.fixture
def make_app(theme, fonts):
    def _make(touch_script=None, mono=1000.0, wall=1_700_000_000.0):
        lcd = FakeLCD()
        touch = ScriptedTouch(touch_script or [])
        clock = FakeClock(mono, wall)
        app = WinterApp(lcd, touch, theme, fonts, clock=clock)
        return app, lcd, touch, clock

    return _make
