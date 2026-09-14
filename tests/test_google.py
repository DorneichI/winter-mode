"""The Google Directions client: URL building, parsing, error mapping."""

import json
import urllib.error
import urllib.parse

import pytest

from wintermode.modules.boston.google import (
    MODES,
    GoogleError,
    Leg,
    directions,
    fmt_miles,
    fmt_minutes,
)


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def ok_body():
    return json.dumps({
        "status": "OK",
        "routes": [{
            "legs": [{
                "departure_time": {"value": 1_750_000_000},
                "arrival_time": {"value": 1_750_001_560},
                "duration": {"value": 1560},
                "steps": [
                    {"travel_mode": "WALKING",
                     "duration": {"value": 240}, "distance": {"value": 320},
                     "html_instructions":
                         "Walk to <b>Hemenway St</b>."},
                    {"travel_mode": "WALKING",
                     "duration": {"value": 60}, "distance": {"value": 40},
                     "html_instructions":
                         "Turn <b>left</b> onto <b>Fenway</b>."},
                    {"travel_mode": "TRANSIT", "transit_details": {
                        "departure_time": {"value": 1_750_000_240},
                        "arrival_time": {"value": 1_750_000_940},
                        "headsign": "Alewife",
                        "line": {"name": "Red Line", "short_name": "Red"},
                        "departure_stop": {"name": "Park Street"},
                        "arrival_stop": {"name": "Kendall/MIT"},
                    }},
                    {"travel_mode": "WALKING",
                     "duration": {"value": 120}, "distance": {"value": 160}},
                ],
            }],
        }],
    }).encode()


def test_directions_url_encodes_every_param():
    seen = {}

    def fetch(url, timeout):
        seen["url"] = url
        return FakeResponse(b"{}")

    with pytest.raises(GoogleError):  # status UNKNOWN_ERROR for the empty body
        directions("100 Main St, Boston", 42.35, -71.06, "transit", "KEY",
                   1_750_000_000, fetch=fetch)
    base, query = seen["url"].split("?")
    assert base == "https://maps.googleapis.com/maps/api/directions/json"
    params = urllib.parse.parse_qs(query)
    assert params["origin"] == ["100 Main St, Boston"]
    assert params["destination"] == ["42.35,-71.06"]
    assert params["mode"] == ["transit"]
    assert params["departure_time"] == ["1750000000"]
    assert params["alternatives"] == ["true"]
    assert params["key"] == ["KEY"]


def test_directions_maps_every_config_mode():
    seen = []

    def fetch(url, timeout):
        seen.append(urllib.parse.parse_qs(url.split("?")[1])["mode"][0])
        return FakeResponse(b'{"status": "OK", "routes": []}')

    for config_mode, _google_mode in MODES.items():
        directions("x", 1, 2, config_mode, "K", 3, fetch=fetch)
    assert seen == ["transit", "walking", "bicycling", "driving"]


def test_directions_parses_legs_and_merges_walking_runs():
    result = directions("addr", 42.35, -71.06, "transit", "K", 0,
                        fetch=lambda url, timeout: FakeResponse(ok_body()))
    (trip,) = result
    assert trip.depart == 1_750_000_000
    # the trailing 2-min walk is a coordinate stub after the final ride:
    # dropped, so the trip ends at the stop and the clock says so
    assert trip.arrive == 1_750_000_940
    assert trip.duration == 1440  # 1560 minus the stubbed walk
    walk1, ride = trip.legs
    assert walk1 == Leg("walk", "walk", "5 min (0.2 mi)", None, None,
                        steps=("Walk to Hemenway St.",
                               "Turn left onto Fenway."),
                        seconds=300, meters=360.0)
    assert ride.mode == "transit"
    assert ride.title == "Red"
    assert ride.detail == "→ Alewife"
    assert ride.start == 1_750_000_240 and ride.end == 1_750_000_940
    assert ride.board == "Park Street"
    assert ride.alight == "Kendall/MIT"


def test_coordinate_stub_walk_after_the_last_ride_is_dropped():
    # tapping a station means the destination IS the station: Google's
    # "walk the last meters to the coordinates" leg must not appear
    body = json.dumps({"status": "OK", "routes": [{"legs": [{
        "arrival_time": {"value": 1_750_001_560},
        "duration": {"value": 1560},
        "steps": [
            {"travel_mode": "TRANSIT", "transit_details": {
                "departure_time": {"value": 1_750_000_000},
                "arrival_time": {"value": 1_750_000_940},
                "headsign": "Alewife", "line": {"short_name": "Red"},
                "departure_stop": {"name": "Park Street"},
                "arrival_stop": {"name": "Central"}}},
            {"travel_mode": "WALKING",
             "duration": {"value": 120}, "distance": {"value": 90}},
        ],
    }]}]}).encode()
    (trip,) = directions("a", 1, 2, "transit", "K", 0,
                         fetch=lambda url, timeout: FakeResponse(body))
    (ride,) = trip.legs
    assert ride.alight == "Central"  # the trip ends on the train
    assert trip.arrive == 1_750_000_940
    assert trip.duration == 1440


def test_transfer_walk_between_rides_stays():
    body = json.dumps({"status": "OK", "routes": [{"legs": [{
        "duration": {"value": 1200},
        "steps": [
            {"travel_mode": "TRANSIT", "transit_details": {
                "departure_time": {"value": 100}, "arrival_time": {"value": 500},
                "headsign": "Govt Center", "line": {"short_name": "C"},
                "departure_stop": {"name": "Fenway"},
                "arrival_stop": {"name": "Government Center"}}},
            {"travel_mode": "WALKING",
             "duration": {"value": 120}, "distance": {"value": 100}},
            {"travel_mode": "TRANSIT", "transit_details": {
                "departure_time": {"value": 700}, "arrival_time": {"value": 900},
                "headsign": "Wonderland", "line": {"short_name": "Blue"},
                "departure_stop": {"name": "Government Center"},
                "arrival_stop": {"name": "Maverick"}}},
        ],
    }]}]}).encode()
    (trip,) = directions("a", 1, 2, "transit", "K", 0,
                         fetch=lambda url, timeout: FakeResponse(body))
    modes = [leg.mode for leg in trip.legs]
    assert modes == ["transit", "walk", "transit"]  # the transfer stays


def test_long_walk_after_the_ride_is_kept():
    # a genuinely distant stop (walk > 300 m) is real, not a stub
    body = json.dumps({"status": "OK", "routes": [{"legs": [{
        "duration": {"value": 1560},
        "steps": [
            {"travel_mode": "TRANSIT", "transit_details": {
                "departure_time": {"value": 100}, "arrival_time": {"value": 500},
                "headsign": "Alewife", "line": {"short_name": "Red"},
                "departure_stop": {"name": "Park Street"},
                "arrival_stop": {"name": "Harvard"}}},
            {"travel_mode": "WALKING",
             "duration": {"value": 600}, "distance": {"value": 800}},
        ],
    }]}]}).encode()
    (trip,) = directions("a", 1, 2, "transit", "K", 0,
                         fetch=lambda url, timeout: FakeResponse(body))
    assert [leg.mode for leg in trip.legs] == ["transit", "walk"]


def test_transit_steps_carry_board_and_alight_stops():
    body = json.dumps({"status": "OK", "routes": [{"legs": [{
        "duration": {"value": 600},
        "steps": [{"travel_mode": "TRANSIT", "transit_details": {
            "departure_time": {"value": 100}, "arrival_time": {"value": 500},
            "headsign": "Wonderland",
            "line": {"short_name": "Blue"},
            "departure_stop": {"name": "Government Center"},
            "arrival_stop": {"name": "Maverick"},
        }}],
    }]}]}).encode()
    (trip,) = directions("a", 1, 2, "transit", "K", 0,
                         fetch=lambda url, timeout: FakeResponse(body))
    (ride,) = trip.legs
    assert ride.board == "Government Center"
    assert ride.alight == "Maverick"


def test_html_instructions_are_plain_text():
    from wintermode.modules.boston.google import _strip_html

    assert _strip_html("Turn <b>left</b> onto <b>Boylston St</b>.") == \
        "Turn left onto Boylston St."
    assert _strip_html("Walk to &amp; around the station") == \
        "Walk to & around the station"


def test_directions_returns_multiple_alternatives_in_order():
    body = json.dumps({"status": "OK", "routes": [
        {"legs": [{"duration": {"value": 600}, "steps": []}]},
        {"legs": [{"duration": {"value": 900}, "steps": []}]},
    ]}).encode()
    trips = directions("a", 1, 2, "transit", "K", 0,
                       fetch=lambda url, timeout: FakeResponse(body))
    assert [trip.duration for trip in trips] == [600, 900]


@pytest.mark.parametrize("status,message", [
    ("ZERO_RESULTS", "no route found to that station"),
    ("NOT_FOUND", "address not found - check it on the web page"),
    ("REQUEST_DENIED",
     "google rejected the api key - check it on the web page"),
    ("OVER_QUERY_LIMIT", "google quota exceeded - try again later"),
    ("UNKNOWN_ERROR", "google returned an unknown error"),
])
def test_directions_maps_status_to_friendly_error(status, message):
    body = json.dumps({"status": status}).encode()
    with pytest.raises(GoogleError) as caught:
        directions("a", 1, 2, "transit", "K", 0,
                   fetch=lambda url, timeout: FakeResponse(body))
    assert caught.value.message == message


def test_directions_network_failure_is_descriptive():
    def fetch(url, timeout):
        raise urllib.error.URLError("refused")

    with pytest.raises(GoogleError) as caught:
        directions("a", 1, 2, "transit", "K", 0, fetch=fetch)
    assert "network" in caught.value.message


def test_directions_unparseable_body_is_descriptive():
    with pytest.raises(GoogleError) as caught:
        directions("a", 1, 2, "transit", "K", 0,
                   fetch=lambda url, timeout: FakeResponse(b"{nope"))
    assert "unreadable" in caught.value.message


@pytest.mark.parametrize("body", [b"[]", b"null", b'"maintenance"',
                                  b'{"status": "OK", "routes": 5}'])
def test_directions_wrong_shape_body_is_descriptive(body):
    """Valid JSON of the wrong shape — a captive portal or a proxy error
    page — must fail as readably as a body that will not parse."""
    with pytest.raises(GoogleError) as caught:
        directions("a", 1, 2, "transit", "K", 0,
                   fetch=lambda url, timeout: FakeResponse(body))
    assert "unreadable" in caught.value.message


def test_directions_null_routes_is_an_empty_result():
    """`routes: null` with an OK status is no itinerary, not a crash:
    the panel turns an empty list into "no route found"."""
    trips = directions("a", 1, 2, "transit", "K", 0,
                       fetch=lambda url, timeout: FakeResponse(
                           b'{"status": "OK", "routes": null}'))
    assert trips == []


def test_fmt_helpers():
    assert fmt_minutes(90) == "2 min"  # rounds, floors at 1
    assert fmt_minutes(10) == "1 min"
    assert fmt_miles(1609.344) == "1.0 mi"
