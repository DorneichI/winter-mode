"""Tap recognition over the FT5x06's raw touch stream.

The panel never reports EVENT_UP: a finger simply disappears from
`Touch.read()`.  So a tap is "down, no meaningful movement, gone within
the window".  Movement beyond TAP_SLOP cancels; a hold longer than
TAP_MAX_MS can never fire; a finger held past the window is marked dead
(still tracked, so its continued presence emits no fresh 'down').

Two-finger rule: a tap is suppressed if another finger is still down at
the moment of release — on multitouch surfaces (phones driving the sim)
that keeps a two-thumb pinch from double-activating UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from ertftm070.touch import TouchPoint

TAP_SLOP = 12  # px of movement that cancels a tap
TAP_MAX_MS = 800  # hold longer than this: the release never fires


@dataclass
class _Finger:
    x0: int
    y0: int
    t0: float
    moved: bool = False


class TapTracker:
    def __init__(self, slop: int = TAP_SLOP, max_ms: int = TAP_MAX_MS) -> None:
        self.slop = slop
        self.max_s = max_ms / 1000.0
        self._fingers: dict[int, _Finger] = {}

    def update(
        self, points: list[TouchPoint], now: float
    ) -> list[tuple[str, int, int]]:
        """Feed the current down-points.  Returns ("down"|"tap", x, y) events."""
        events: list[tuple[str, int, int]] = []
        present = {p.id for p in points}

        # new contacts
        for p in points:
            finger = self._fingers.get(p.id)
            if finger is None:
                self._fingers[p.id] = _Finger(p.x, p.y, now)
                events.append(("down", p.x, p.y))
            elif not finger.moved and abs(p.x - finger.x0) + abs(
                p.y - finger.y0
            ) > self.slop:
                finger.moved = True

        # holds past the window go dead (never fire, no fresh 'down' events)
        for finger in self._fingers.values():
            if not finger.moved and now - finger.t0 > self.max_s:
                finger.moved = True

        # releases: present last poll, absent now
        for fid in list(self._fingers):
            if fid not in present:
                finger = self._fingers.pop(fid)
                if (
                    not finger.moved
                    and now - finger.t0 <= self.max_s
                    and not present  # no second finger down at release
                ):
                    events.append(("tap", finger.x0, finger.y0))

        return events
