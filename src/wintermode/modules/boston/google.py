"""Google Maps Directions API client — pure functions, stdlib only.

The device has no HTTP client dependency, so this speaks urllib and
returns plain dataclasses; every failure is a GoogleError with a
message a person can read on the panel.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"

# config-level mode name -> Directions API mode parameter
MODES = {
    "transit": "transit",
    "walk": "walking",
    "bike": "bicycling",
    "car": "driving",
}

# a body that is not the response we asked for: unparseable, or valid
# JSON of the wrong shape (captive portal, proxy error page, truncation)
_UNREADABLE = "unreadable response from google maps"

# the status field of a non-OK response -> panel-friendly message
_STATUS_MESSAGES = {
    "ZERO_RESULTS": "no route found to that station",
    "NOT_FOUND": "address not found - check it on the web page",
    "INVALID_REQUEST": "request rejected - check the address and api key",
    "REQUEST_DENIED": "google rejected the api key - check it on the web page",
    "OVER_QUERY_LIMIT": "google quota exceeded - try again later",
    "UNKNOWN_ERROR": "google returned an unknown error",
}


class GoogleError(Exception):
    """A trip query failure, carrying a user-facing message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Leg:
    """One row of an itinerary: a walk/drive/bike run or one transit ride.

    `start`/`end` are epoch seconds; None for non-transit runs, which
    the panel shows as "walk 3 min" without clock times.  Transit legs
    carry the board/alight stops; street legs carry Google's
    step-by-step instructions (street by street directions).
    """

    mode: str  # walk | transit | car | bike
    title: str  # e.g. "RED LINE" / "walk"
    detail: str  # e.g. "→ ALEWIFE" / "3 min (0.2 mi)"
    start: int | None
    end: int | None
    board: str | None = None  # transit: the stop you get on at
    alight: str | None = None  # transit: the stop you get off at
    steps: tuple = ()  # walk/drive/bike: street by street instructions
    seconds: int = 0  # street legs: duration, for trip arithmetic
    meters: float = 0.0  # street legs: distance, to spot coordinate stubs


@dataclass(frozen=True)
class Itinerary:
    depart: int  # epoch seconds
    arrive: int  # epoch seconds
    duration: int  # seconds
    legs: tuple[Leg, ...]


def fmt_clock(epoch: int | None) -> str:
    """`epoch` -> "14:02" panel text; None -> "     "."""
    if epoch is None:
        return "     "
    return time.strftime("%H:%M", time.localtime(epoch))


def fmt_minutes(seconds: float) -> str:
    return f"{max(1, round(seconds / 60))} min"


def fmt_miles(meters: float) -> str:
    return f"{meters / 1609.344:.1f} mi"


def _default_fetch(url: str, timeout: float):
    return urllib.request.urlopen(urllib.request.Request(url),
                                  timeout=timeout)


def directions(origin: str, dest_lat: float, dest_lon: float, mode: str,
               api_key: str, depart_epoch: float, *, fetch=None,
               timeout: float = 10.0) -> list[Itinerary]:
    """Plan a trip from a free-text address to lat/lon, leaving now.

    `fetch` is injectable for tests — a callable (url, timeout) ->
    file-like whose read() returns the JSON body.  The default is
    urllib; every failure path raises GoogleError with a message.
    """
    params = {
        "origin": origin,
        "destination": f"{dest_lat},{dest_lon}",
        "mode": MODES[mode],
        "departure_time": str(int(depart_epoch)),
        "alternatives": "true",
        "key": api_key,
    }
    url = DIRECTIONS_URL + "?" + urllib.parse.urlencode(params)
    try:
        opener = fetch or _default_fetch
        with opener(url, timeout) as response:
            body = response.read()
    except Exception:
        raise GoogleError("can't reach google maps - check the network") \
            from None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        raise GoogleError(_UNREADABLE) from None
    if not isinstance(data, dict):
        raise GoogleError(_UNREADABLE)
    status = data.get("status", "UNKNOWN_ERROR")
    if status != "OK":
        raise GoogleError(_STATUS_MESSAGES.get(status, "google error"))
    routes = data.get("routes") or []
    if not isinstance(routes, list):
        raise GoogleError(_UNREADABLE)
    return [_parse_route(route) for route in routes]


def _strip_html(markup) -> str:
    """Google's html_instructions -> plain text ("Turn left onto X St")."""
    return html.unescape(re.sub(r"<[^>]+>", "", markup or "")).strip()


def _parse_route(route: dict) -> Itinerary:
    """One route -> one Itinerary; steps merge into run-length legs.

    Consecutive non-transit steps of the same mode collapse into a
    single summary Leg that carries each step's street-by-street
    instruction, and each transit step becomes its own Leg with board
    and alight stops and times.
    """
    legs: list[Leg] = []
    run: dict | None = None  # mode -> accumulated secs/meters/steps

    def flush() -> None:
        nonlocal run
        if run is None:
            return
        mode = run["mode"]
        label = {"WALKING": "walk", "DRIVING": "car", "BICYCLING": "bike"}
        legs.append(Leg(label.get(mode, "walk"),
                        label.get(mode, "walk"),
                        f"{fmt_minutes(run['seconds'])} "
                        f"({fmt_miles(run['meters'])})",
                        None, None, steps=tuple(run["steps"]),
                        seconds=run["seconds"], meters=run["meters"]))
        run = None

    depart = arrive = None
    total_seconds = 0.0
    for leg in route.get("legs", []):
        if depart is None:
            depart = (leg.get("departure_time") or {}).get("value")
        arrive = (leg.get("arrival_time") or {}).get("value")
        total_seconds += (leg.get("duration") or {}).get("value", 0)
        for step in leg.get("steps", []):
            mode = step.get("travel_mode", "WALKING")
            if mode == "TRANSIT":
                flush()
                details = step.get("transit_details", {})
                line = details.get("line", {})
                title = line.get("short_name") or line.get("name") or "T"
                headsign = details.get("headsign", "")
                board = (details.get("departure_stop") or {}).get("name")
                alight = (details.get("arrival_stop") or {}).get("name")
                legs.append(Leg(
                    "transit", str(title),
                    f"→ {headsign}" if headsign else "",
                    (details.get("departure_time") or {}).get("value"),
                    (details.get("arrival_time") or {}).get("value"),
                    board=board, alight=alight,
                ))
                continue
            if run is None or run["mode"] != mode:
                flush()
                run = {"mode": mode, "seconds": 0.0, "meters": 0.0,
                       "steps": []}
            run["seconds"] += (step.get("duration") or {}).get("value", 0)
            run["meters"] += (step.get("distance") or {}).get("value", 0)
            instruction = _strip_html(step.get("html_instructions"))
            if instruction:
                run["steps"].append(instruction)
    flush()

    # the destination IS the station, so Google's trailing "walk the
    # last few meters to the coordinates" after the final ride is an
    # artifact of routing to lat/lon: drop it and end the trip at the
    # stop.  Transfer walks sit between rides and long walks mean the
    # nearest stop is genuinely elsewhere — both stay.
    if len(legs) >= 2 and legs[-1].mode != "transit" \
            and legs[-1].meters <= 300 and legs[-2].mode == "transit":
        dropped = legs.pop()
        total_seconds -= dropped.seconds
        if legs[-1].end is not None:
            arrive = legs[-1].end

    return Itinerary(depart or 0, arrive or 0, int(total_seconds),
                     tuple(legs))
