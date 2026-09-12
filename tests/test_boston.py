"""The boston module: map, hitboxes, and the trip alert state machine."""

import json
import math
import threading

import pytest
from PIL import Image, ImageDraw

from wintermode.modules.boston import google
from wintermode.modules.boston import module as boston_mod
from wintermode.modules.boston.google import GoogleError, Itinerary, Leg
from wintermode.modules.boston.module import (
    LINE_COLORS,
    MODES,
    SCHEMA,
    Boston,
    TripAlert,
)


@pytest.fixture
def boston():
    """A fresh Boston module; tests swap _fetch before any tap."""
    return Boston()


@pytest.fixture
def trips_fetch():
    """A scriptable fetch: records calls, optionally blocks the first."""

    class FakeFetch:
        def __init__(self, trips=None, error=None):
            self.calls = []
            self.trips = trips or []
            self.error = error
            self.first = threading.Event()
            self.release = None  # set per test: "block" or "release"

        def __call__(self, address, lat, lon, mode, key, epoch):
            self.calls.append({"address": address, "lat": lat, "lon": lon,
                               "mode": mode, "key": key})
            if len(self.calls) == 1 and self.release is not None:
                self.release.wait(timeout=5)
            if self.error:
                raise GoogleError(self.error)
            return list(self.trips)

    return FakeFetch


def trip(legs, duration=1560, arrive=1_750_001_560):
    return Itinerary(1_750_000_000, arrive, duration, tuple(legs))


def walk_leg(seconds=180):
    return Leg("walk", "walk", f"{seconds // 60} min (0.2 mi)", None, None)


def make_ctx(ctx, config):
    """A ctx whose config carries boston settings."""
    config.update({"boston": {"address": "100 Main St, Boston",
                              "mode": "transit", "api_key": "KEY"}})
    return ctx(registry=None)


def canvas():
    image = Image.new("RGB", (800, 480), (0, 0, 0))
    return image, ImageDraw.Draw(image)


def alert_on_stack(ctx):
    assert len(ctx.nav) == 2
    return ctx.nav.top


def tap_rect(view, rect, ctx):
    assert view.on_tap((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2,
                       ctx) is True


def tap_footer(alert, action, ctx):
    rect = alert._footer[action]
    assert rect is not None, f"{action!r} button should be tappable"
    tap_rect(alert, rect, ctx)


def render(view, ctx):
    _, draw = canvas()
    view.render(draw, ctx)


# --- graph -------------------------------------------------------------------


def test_graph_covers_all_four_lines(boston):
    assert len(boston._stations) == 118
    assert len(boston._edges) == 119
    for _a, _b, colors in boston._edges:
        assert colors and all(c in LINE_COLORS for c in colors)
    multi = [e for e in boston._edges if len(e[2]) > 1]
    assert len(multi) == 1
    a, b, colors = multi[0]
    assert {a["id"], b["id"]} == {"haymarket", "north_station"}
    assert colors == ["orange", "green"]


def test_every_station_has_coordinates(boston):
    for v in boston._stations.values():
        assert v["name"] and v["id"]
        assert 41.0 < v["lat"] < 43.5 and -72.0 < v["lon"] < -69.0
        assert 0.0 <= v["x"] <= 1.0 and 0.0 <= v["y"] <= 1.0


def test_bad_graph_entries_are_skipped(boston, tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "vertices": [
            {"id": "ok", "name": "OK", "x": 0.5, "y": 0.5,
             "lat": 42.0, "lon": -71.0},
            {"id": "no_name"},  # missing fields
            {"id": "clamp", "name": "CL", "x": 9.0, "y": -2.0,
             "lat": 42.1, "lon": -71.1},  # out-of-range x/y clamp
            {"id": "badlat", "name": "BL", "x": 0.5, "y": 0.5,
             "lat": "nope", "lon": -71.0},  # unparsable lat
        ],
        "edges": [
            {"a": "ok", "b": "ghost", "colors": ["red"]},  # unknown endpoint
            {"a": "ok", "b": "ok", "colors": ["red"]},  # self loop
            {"a": "ok", "b": "clamp", "colors": ["pink"]},  # unknown color
        ],
    }))
    monkeypatch.setattr(boston_mod, "GRAPH_PATH", bad)
    module = Boston()
    assert set(module._stations) == {"ok", "clamp"}
    assert module._stations["clamp"]["x"] == 1.0  # clamped, not rejected
    assert module._stations["clamp"]["y"] == 0.0
    assert module._edges == []


def test_map_render_builds_a_hitbox_per_station(boston, theme, fonts, ctx):
    c = ctx(registry=None)
    _, draw = canvas()
    assert boston.render(draw, c) is True
    assert len(boston._hitboxes) == len(boston._stations)
    for rect, vid in boston._hitboxes.items():
        station = boston._stations[vid]
        cx, cy = boston._place(station, c)
        assert rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def test_map_draws_line_colors(boston, theme, fonts, ctx):
    c = ctx(registry=None)
    image, draw = canvas()
    boston.render(draw, c)
    colors = {image.getpixel((x, y)) for x in range(800) for y in range(480)}
    for rgb in LINE_COLORS.values():
        assert rgb in colors


# --- trip flow ----------------------------------------------------------------


def test_station_tap_pushes_confirm_alert(boston, trips_fetch, theme, fonts,
                                          ctx, config):
    fetch = trips_fetch()
    fetch.release = None
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    assert isinstance(alert, TripAlert)
    assert alert._state == "confirm"
    assert alert._mode == "transit"
    assert fetch.calls and fetch.calls[0]["lat"] == pytest.approx(42.356395)


def test_tap_picks_nearest_station_not_first_hitbox(boston, trips_fetch,
                                                    theme, fonts, ctx,
                                                    config):
    """Downtown stations sit closer than a hitbox apart; the nearest
    station center must win, not hitbox insertion order."""
    fetch = trips_fetch()
    fetch.release = None
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    park = boston._stations["park_street"]
    charles = boston._stations["charles_mgh"]
    px, py = boston._place(park, c)
    nx, ny = boston._place(charles, c)
    assert math.hypot(px - nx, py - ny) < 2 * 22  # hitboxes overlap
    # three quarters of the way from charles to park: park is nearest
    tx, ty = int((3 * px + nx) / 4), int((3 * py + ny) / 4)
    assert boston.on_tap(tx, ty, c) is True
    assert fetch.calls[0]["lat"] == pytest.approx(42.356395)


def test_tap_without_address_shows_descriptive_error(boston, trips_fetch,
                                                     theme, fonts, ctx,
                                                     config):
    fetch = trips_fetch()
    boston._fetch = fetch
    c = ctx(registry=None)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    assert alert._state == "error"
    assert "address" in alert._error
    assert fetch.calls == []  # nothing queried


def test_tap_without_key_shows_descriptive_error(boston, trips_fetch, theme,
                                                 fonts, ctx, config):
    fetch = trips_fetch()
    boston._fetch = fetch
    config.update({"boston": {"address": "100 Main St, Boston",
                              "mode": "transit", "api_key": ""}})
    c = ctx(registry=None)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    assert alert._state == "error"
    assert "api key" in alert._error
    assert fetch.calls == []


def test_ok_with_unchanged_mode_waits_for_inflight_query(
        boston, trips_fetch, theme, fonts, ctx, config):
    fetch = trips_fetch(trips=[trip([walk_leg()])])
    fetch.release = threading.Event()  # hold the query open
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    tap_footer(alert, "ok", c)
    assert alert._state == "computing"
    assert len(fetch.calls) == 1  # no re-query: mode unchanged
    fetch.release.set()  # the result arrives now
    render(alert, c)
    assert alert._state == "results"
    assert len(alert._trips) == 1


def test_ok_with_changed_mode_requeries(
        boston, trips_fetch, theme, fonts, ctx, config):
    fetch = trips_fetch(trips=[trip([walk_leg(120)])])
    fetch.release = threading.Event()  # the default-mode query never lands
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    tap_rect(alert, alert._mode_rect, c)  # cycle transit -> walk
    assert alert._mode == "walk"
    tap_footer(alert, "ok", c)
    assert alert._state == "computing"
    assert [call["mode"] for call in fetch.calls] == ["transit", "walk"]
    render(alert, c)
    assert alert._state == "results"  # the walk query answered


def test_cancel_abandons_and_stale_result_is_dropped(
        boston, trips_fetch, theme, fonts, ctx, config):
    fetch = trips_fetch(trips=[trip([walk_leg()])])
    fetch.release = threading.Event()
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    tap_footer(alert, "cancel", c)
    assert len(c.nav) == 1  # popped back to the map
    fetch.release.set()  # the abandoned result lands late
    render(boston, c)  # the module keeps rendering regardless
    assert boston._alert is None


def test_bar_back_pop_abandons_the_query(boston, trips_fetch, theme, fonts,
                                         ctx, config):
    fetch = trips_fetch(trips=[trip([walk_leg()])])
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    seq = alert._seq
    c.nav.pop()  # what the bar's [‹ BACK] does
    render(boston, c)
    assert boston._alert is None
    assert boston._seq > seq  # the in-flight result is stale


def test_web_abandon_action_pops_the_alert(boston, trips_fetch, theme, fonts,
                                           ctx, config):
    fetch = trips_fetch(trips=[trip([walk_leg()])])
    fetch.release = threading.Event()
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    boston.on_action("abandon", c)
    render(alert, c)  # notices the seq moved and pops itself
    assert len(c.nav) == 1


def test_results_arrows_cycle_itineraries(boston, trips_fetch, theme, fonts,
                                          ctx, config):
    trips = [trip([walk_leg(180)], duration=600),
             trip([walk_leg(300)], duration=1200)]
    fetch = trips_fetch(trips=trips)
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    tap_footer(alert, "ok", c)  # result already pending -> results
    render(alert, c)
    assert alert._state == "results"
    assert alert._footer["<"] is None  # first itinerary: < grey and inert
    tap_footer(alert, ">", c)
    render(alert, c)
    assert alert._index == 1
    assert alert._footer[">"] is None  # last itinerary: > grey and inert
    tap_footer(alert, "done", c)
    assert len(c.nav) == 1


def test_long_leg_list_gets_scroll_buttons(boston, trips_fetch, theme, fonts,
                                           ctx, config):
    legs = [walk_leg(60) for _ in range(15)]
    fetch = trips_fetch(trips=[trip(legs)])
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    tap_footer(alert, "ok", c)
    render(alert, c)
    assert alert._state == "results"
    assert alert._scroller["down"] is not None
    assert alert._scroller["up"] is None
    tap_rect(alert, alert._scroller["down"], c)
    render(alert, c)
    assert alert._leg_offset == 1
    # scrolling to the end leaves only the up button
    alert._leg_offset = len(legs)
    render(alert, c)
    assert alert._scroller["up"] is not None
    assert alert._scroller["down"] is None


def test_query_error_shows_descriptive_alert(boston, trips_fetch, theme,
                                             fonts, ctx, config):
    fetch = trips_fetch(error="no route found to that station")
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    # the error surfaces immediately, even while confirming
    render(alert, c)
    assert alert._state == "error"
    assert alert._error == "no route found to that station"
    tap_footer(alert, "done", c)
    assert len(c.nav) == 1


def test_transit_leg_rows_name_board_and_alight_stops():
    from wintermode.modules.boston.module import TripAlert

    rides = trip([
        Leg("transit", "Blue", "→ Wonderland", 1_750_000_500, 1_750_001_000,
            board="Government Center", alight="Maverick"),
    ])
    alert = TripAlert.__new__(TripAlert)  # no module wiring needed
    rows = alert._leg_rows(rides)
    assert "BLUE → WONDERLAND" in rows[0]
    assert "BOARD GOVERNMENT CENTER" in rows[1]
    assert "OFF MAVERICK" in rows[1]


def test_walking_leg_rows_include_street_directions():
    from wintermode.modules.boston.module import TripAlert

    walks = trip([
        Leg("walk", "walk", "8 min (0.3 mi)", None, None,
            steps=("Walk to Hemenway St", "Turn left onto Fenway")),
    ])
    alert = TripAlert.__new__(TripAlert)
    rows = alert._leg_rows(walks)
    assert rows[0] == "WALK 8 MIN (0.3 MI)"
    assert rows[1] == "  WALK TO HEMENWAY ST"
    assert rows[2] == "  TURN LEFT ONTO FENWAY"


def test_empty_trip_list_reads_as_no_route(boston, trips_fetch, theme, fonts,
                                           ctx, config):
    fetch = trips_fetch(trips=[])
    boston._fetch = fetch
    c = make_ctx(ctx, config)
    render(boston, c)
    rect = next(r for r, vid in boston._hitboxes.items()
                if vid == "park_street")
    tap_rect(boston, rect, c)
    alert = alert_on_stack(c)
    render(alert, c)
    tap_footer(alert, "ok", c)  # zero routes surface on confirm
    render(alert, c)
    assert alert._state == "error"
    assert "no route" in alert._error


# --- module contract -----------------------------------------------------------


def test_status_items_show_address(boston, theme, fonts, ctx, config):
    c = make_ctx(ctx, config)
    (item,) = boston.status_items(c)
    assert "100 Main St" in item.text


def test_status_items_without_address(boston, theme, fonts, ctx, config):
    c = ctx(registry=None)
    (item,) = boston.status_items(c)
    assert "no address" in item.text


def test_schema_covers_address_mode_and_key():
    assert set(SCHEMA) == {"address", "mode", "api_key"}
    assert SCHEMA["mode"]["options"] == list(MODES)
    assert SCHEMA["mode"]["default"] == "transit"
    # the key is a secret: write-only, never shown anywhere
    assert SCHEMA["api_key"]["write_only"] is True
    # both are local: stored in the gitignored overlay, never committed
    assert SCHEMA["api_key"]["local"] is True
    assert SCHEMA["address"]["local"] is True


def test_module_contract_is_complete(boston):
    assert boston.id == "boston"
    assert boston.title == "BOSTON"
    assert boston.interval == 0
    assert [a["id"] for a in boston.actions] == ["abandon", "reload"]


def test_fmt_clock_imported_for_rows():
    assert google.fmt_clock(1_750_001_560) != ""
