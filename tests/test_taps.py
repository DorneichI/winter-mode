"""TapTracker: the FT5x06 never reports EVENT_UP — a finger disappears."""

from ertftm070.touch import EVENT_CONTACT

from wintermode.taps import TapTracker


def test_tap_fires_on_release(point):
    t = TapTracker()
    assert t.update([point(10, 10)], 0.0) == [("down", 10, 10)]
    assert t.update([], 0.1) == [("tap", 10, 10)]


def test_movement_beyond_slop_cancels(point):
    t = TapTracker()
    t.update([point(10, 10)], 0.0)
    t.update([point(30, 30, event=EVENT_CONTACT)], 0.05)  # 40 > 12 slop
    assert t.update([], 0.1) == []


def test_hold_longer_than_window_never_fires(point):
    t = TapTracker()
    t.update([point(10, 10)], 0.0)
    assert t.update([], 0.9) == []  # released after 900 ms


def test_hold_that_outlives_the_window_is_dead_and_still_does_not_fire(point):
    # the re-arm trap: a finger held forever must neither re-emit 'down'
    # nor fire a tap when it finally releases
    t = TapTracker()
    assert t.update([point(10, 10)], 0.0) == [("down", 10, 10)]
    for i in range(1, 30):
        events = t.update([point(10, 10, event=EVENT_CONTACT)], i * 0.1)
        assert not events, events  # no fresh 'down' events while held
    assert t.update([], 3.1) == []


def test_two_fingers_sequence_fires_two_taps_in_order(point):
    t = TapTracker()
    t.update([point(10, 10, 0)], 0.0)
    assert t.update([], 0.1) == [("tap", 10, 10)]
    t.update([point(50, 50, 1)], 0.2)
    assert t.update([], 0.3) == [("tap", 50, 50)]


def test_tap_suppressed_while_second_finger_down(point):
    t = TapTracker()
    t.update([point(10, 10, 0)], 0.0)
    t.update(
        [point(10, 10, 0, event=EVENT_CONTACT), point(400, 400, 1)], 0.05
    )
    assert t.update([point(400, 400, 1, event=EVENT_CONTACT)], 0.1) == []


def test_two_fingers_down_never_leave_a_tap_behind(point):
    # thumbs lifting one poll apart: the first release is suppressed (a
    # finger is still down) but the second used to fire a tap on
    # whatever it happened to be resting on
    tracker = TapTracker()
    tracker.update([point(100, 100, fid=1), point(300, 300, fid=2)], 100.0)
    held = [point(300, 300, fid=2, event=EVENT_CONTACT)]
    assert tracker.update(held, 100.1) == []
    assert tracker.update([], 100.2) == []


def test_empty_polls_emit_nothing(point):
    t = TapTracker()
    assert t.update([], 0.0) == []
    assert t.update([], 0.5) == []


def test_small_movement_within_slop_still_fires(point):
    t = TapTracker()
    t.update([point(10, 10)], 0.0)
    t.update([point(14, 16, event=EVENT_CONTACT)], 0.05)  # |dx|+|dy| = 10
    assert t.update([], 0.1) == [("tap", 10, 10)]


def test_two_fingers_lifting_in_one_poll_fire_no_tap(point):
    # a two-thumb pinch releasing both thumbs inside the same read():
    # "no finger down at release" is true for BOTH, so the per-finger
    # rule alone fired two taps for one gesture
    tracker = TapTracker()
    both = [point(100, 100, fid=1), point(300, 300, fid=2)]
    tracker.update(both, 100.0)
    assert tracker.update([], 100.1) == []
