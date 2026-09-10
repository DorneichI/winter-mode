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
        self.sleep_calls = 0
        self.wake_calls = 0
        self.backlight_calls: list[bool] = []

    def image(self, img: Image.Image, x: int = 0, y: int = 0, **kw) -> None:
        self.calls.append(img.copy())

    def sleep(self) -> None:
        self.sleep_calls += 1

    def wake(self) -> None:
        self.wake_calls += 1

    def backlight(self, on: bool) -> None:
        self.backlight_calls.append(on)


class ScriptedTouch:
    """read() returns scripted point-lists per call, then empty.
    wait_touch() consumes the next script entry and reports whether it
    held any points — the run() loop's asleep branch."""

    def __init__(self, script: list[list[TouchPoint]]) -> None:
        self.script = list(script)
        self.i = 0

    def read(self, mapped: bool = True) -> list[TouchPoint]:
        if self.i >= len(self.script):
            return []
        points = self.script[self.i]
        self.i += 1
        return points

    def wait_touch(self, timeout: float | None = None,
                   poll_interval: float = 0.02) -> bool:
        if self.i >= len(self.script):
            return False
        points = self.script[self.i]
        self.i += 1
        return bool(points)


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


class FakeModule:
    """A minimal module object speaking the whole contract."""

    def __init__(self, module_id, title=None, config_schema=None,
                 actions=None, interval=0):
        self.id = module_id
        self.title = title or module_id.upper()
        self.interval = interval
        self.config_schema = config_schema
        self.actions = actions or []

    def render(self, draw, ctx):
        return True

    def on_tap(self, x, y, ctx):
        return False

    def status_items(self, ctx):
        return []

    def on_action(self, action_id, ctx):
        pass


@pytest.fixture
def fake_module():
    return FakeModule


@pytest.fixture
def config(tmp_path):
    from wintermode.config import Config

    return Config(tmp_path / "config.json")


@pytest.fixture
def registry(config, fake_module):
    from wintermode.registry import Registry

    def _make(ids):
        return Registry([fake_module(i) for i in ids], config)

    return _make


@pytest.fixture
def make_app(theme, fonts, config, fake_module):
    from wintermode.registry import Registry

    def _make(touch_script=None, mono=1000.0, wall=1_700_000_000.0,
              registry=None):
        lcd = FakeLCD()
        touch = ScriptedTouch(touch_script or [])
        clock = FakeClock(mono, wall)
        if registry is None:
            registry = Registry([fake_module("clock"), fake_module("boston")],
                                config)
        app = WinterApp(lcd, touch, theme, fonts, clock=clock,
                        config=config, registry=registry)
        return app, lcd, touch, clock

    return _make


@pytest.fixture
def ctx(theme, fonts, config):
    from wintermode.context import Ctx, Nav
    from wintermode.views import HomeView

    def _make(registry=None, wall: float = 0.0):
        nav = Nav(HomeView(registry=registry, config=config))
        return Ctx(
            theme=theme, fonts=fonts, nav=nav,
            content=(0, 30, 800, 480), width=800, height=480,
            config=config, registry=registry, wall=wall,
        )

    return _make
