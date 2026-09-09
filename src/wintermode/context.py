"""The render/tap context handed to every view and module.

Views never touch the app or the display directly — everything they may
draw with or act on arrives via Ctx.  Background threads may read module
state, but ALL drawing happens on the main loop thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wintermode.fonts import Fonts
from wintermode.theme import Theme


class Nav:
    """A minimal view stack.  `changed` is set by push/pop/home so the
    app can re-render exactly when the stack actually moved."""

    def __init__(self, root: Any) -> None:
        self._stack: list[Any] = [root]
        self.changed = False

    @property
    def top(self) -> Any:
        return self._stack[-1]

    @property
    def stack(self) -> list[Any]:
        return list(self._stack)

    def __len__(self) -> int:
        return len(self._stack)

    def push(self, view: Any) -> None:
        self._stack.append(view)
        self.changed = True

    def pop(self) -> None:
        if len(self._stack) > 1:
            self._stack.pop()
            self.changed = True

    def home(self) -> None:
        if len(self._stack) > 1:
            self._stack = self._stack[:1]
            self.changed = True


@dataclass(frozen=True)
class BarItem:
    """A single status-bar item published by a module."""

    text: str


@dataclass
class Ctx:
    theme: Theme
    fonts: Fonts
    nav: Nav
    content: tuple[int, int, int, int]  # x0, y0, x1, y1 — below the bar
    width: int
    height: int
    points: list = field(default_factory=list)  # live touch points
    now: float = 0.0  # monotonic seconds, for tap timing
    wall: float = 0.0  # wall-clock seconds, for display/formatting
    config: Any = None  # the Config instance
    registry: Any = None  # the module registry
