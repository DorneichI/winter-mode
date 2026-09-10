"""Tap recognition over the FT5x06's raw touch stream.

The panel never reports EVENT_UP: a finger simply disappears from
`Touch.read()`.  So a tap is "down, no meaningful movement, gone within
the window".  Movement beyond TAP_SLOP cancels; a hold longer than
TAP_MAX_MS can never fire; a finger held past the window is marked dead
(still tracked, so its continued presence emits no fresh 'down').

Two-finger rule: a tap is suppressed if another finger is still down at
the moment of release, and a poll that loses more than one finger at once
is a pinch — on multitouch surfaces (phones driving the sim) that keeps a
two-thumb pinch from double-activating UI, including when both thumbs
lift inside the same poll.
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

    def seed(self, points: list[TouchPoint], now: float) -> None:
        """Register already-down fingers as dead: their release fires
        nothing.  Used at wake-up so the waking tap never activates UI."""
        for point in points:
            self._fingers[point.id] = _Finger(point.x, point.y, now, moved=True)

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

        # two fingers down at once is a gesture, not two taps: mark both
        # dead for good, so a pinch whose thumbs lift one poll apart
        # cannot activate whatever the second thumb happens to rest on
        if len(present) > 1:
            for finger in self._fingers.values():
                finger.moved = True

        # holds past the window go dead (never fire, no fresh 'down' events)
        for finger in self._fingers.values():
            if not finger.moved and now - finger.t0 > self.max_s:
                finger.moved = True

        # releases: present last poll, absent now.  Collect them first:
        # when two fingers lift inside the SAME poll, "no finger down at
        # release" is true for both, so the per-finger check alone would
        # fire two taps for one pinch.
        released: list[tuple[str, int, int]] = []
        for fid in list(self._fingers):
            if fid not in present:
                finger = self._fingers.pop(fid)
                if (
                    not finger.moved
                    and now - finger.t0 <= self.max_s
                    and not present  # no second finger down at release
                ):
                    released.append(("tap", finger.x0, finger.y0))
        # more than one finger lifting in one poll is a pinch, never a tap
        if len(released) == 1:
            events.extend(released)

        return events
