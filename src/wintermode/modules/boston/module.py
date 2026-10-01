"""The boston module: an MBTA map + Google Maps trip planning.

The map is a static graph file (vertices with a name, a normalized x/y
position and real lat/lon; edges carry the line colors sharing that
track).  Every station is a circle button: tapping one starts a trip
query in the background (leaving now, settings-default mode) and pushes
a TripAlert that guides confirm -> computing -> results, with a
descriptive error state for every failure.

Threading follows the app contract: only the main loop draws; the query
threads fetch and parse, then hand results over through a queue keyed
by a generation counter, so abandoned queries are dropped on sight.
"""

from __future__ import annotations

import json
import logging
import math
import queue
import textwrap
import threading
import time
from pathlib import Path

from wintermode.context import BarItem, Ctx
from wintermode.fonts import SIZE_FORM
from wintermode.views import ROW_H
from wintermode.widgets import (
    draw_button,
    draw_button_auto,
    draw_circle,
    draw_scroller,
    text_y,
    truncate,
)

from . import google
from .google import GoogleError, fmt_clock, fmt_minutes

log = logging.getLogger(__name__)

GRAPH_PATH = Path(__file__).parent / "graph.json"

# MBTA line colors: red #DA291C, orange #ED8B00, blue #003DA5, green #00843D
LINE_COLORS = {
    "red": (218, 41, 28),
    "orange": (237, 139, 0),
    "blue": (0, 61, 165),
    "green": (0, 132, 61),
}

MODES = ("transit", "walk", "bike", "car")

SCHEMA = {
    # local: stored in the gitignored config.local.json overlay, never
    # in the tracked config.json
    "address": {"type": "text", "title": "Address", "maxlength": 120,
                "default": "", "local": True},
    "mode": {"type": "choice", "title": "Mode", "options": list(MODES),
             "default": "transit"},
    # local + write_only: the web and panel never show a stored key,
    # only offer to set a new one or reset it
    "api_key": {"type": "text", "title": "Google API key", "maxlength": 64,
                "default": "", "write_only": True, "local": True},
}

STATION_RADIUS = 8
HIT_PAD = 22  # half-size of the tap target around a station
EDGE_WIDTH = 4

HEADER_H = 44
FOOTER_H = 44
SCROLLER_H = 26
BODY_MARGIN = 8


def _inside(rect, x: int, y: int) -> bool:
    return rect is not None and rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


class Boston:
    id = "boston"
    title = "BOSTON"
    interval = 0
    config_schema = SCHEMA
    actions = [{"id": "abandon", "title": "Abandon trip"}]

    def __init__(self) -> None:
        self._stations: dict[str, dict] = {}
        self._edges: list[tuple[dict, dict, list[str]]] = []
        self._load_graph()
        self._hitboxes: dict[tuple, str] = {}
        self._alert: TripAlert | None = None
        self._seq = 0  # query generation counter
        self._queue: queue.Queue = queue.Queue()
        self._fetch = google.directions  # tests swap this

    # --- graph -------------------------------------------------------------

    def _read_graph(self) -> tuple[dict, list]:
        """Parse graph.json into (stations, edges), skipping bad entries.

        A bad file yields an empty map rather than an exception: this
        runs at import time, and a traceback here would take the whole
        module off the grid.
        """
        stations: dict[str, dict] = {}
        edges: list[tuple] = []
        try:
            raw = json.loads(GRAPH_PATH.read_text())
        except (OSError, ValueError):
            log.exception("boston: unreadable graph %s", GRAPH_PATH)
            return stations, edges
        if not isinstance(raw, dict):
            log.error("boston: graph %s is not an object", GRAPH_PATH)
            return stations, edges
        vertices = raw.get("vertices")
        if not isinstance(vertices, list):
            log.error("boston: graph %s has no vertices list", GRAPH_PATH)
            return stations, edges
        for entry in vertices:
            try:
                vid = str(entry["id"])
                station = {
                    "id": vid,
                    "name": str(entry["name"]),
                    "x": min(max(float(entry["x"]), 0.0), 1.0),
                    "y": min(max(float(entry["y"]), 0.0), 1.0),
                    "lat": float(entry["lat"]),
                    "lon": float(entry["lon"]),
                }
            except (KeyError, TypeError, ValueError):
                log.warning("boston: skipping bad vertex %r", entry)
                continue
            stations[vid] = station
        for edge in raw.get("edges") or []:
            try:
                a = stations.get(edge["a"])
                b = stations.get(edge["b"])
                colors = [c for c in edge.get("colors", [])
                          if c in LINE_COLORS]
            except (TypeError, AttributeError):
                log.warning("boston: skipping bad edge %r", edge)
                continue
            if a is None or b is None or a is b:
                log.warning("boston: skipping edge with unknown endpoint %r",
                            edge)
                continue
            if not colors:
                log.warning("boston: skipping edge without colors %r", edge)
                continue
            edges.append((a, b, colors))
        return stations, edges

    def _load_graph(self) -> None:
        self._stations, self._edges = self._read_graph()

    # --- map ---------------------------------------------------------------

    def _place(self, v: dict, ctx: Ctx) -> tuple[float, float]:
        x0, y0, x1, y1 = ctx.content
        pad_x, pad_y = 10, 10
        return (x0 + pad_x + v["x"] * (x1 - x0 - 2 * pad_x),
                y0 + pad_y + v["y"] * (y1 - y0 - 2 * pad_y))

    def render(self, draw, ctx: Ctx) -> bool:
        self._note_alert_gone(ctx)
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        for a, b, colors in self._edges:
            self._draw_edge(draw, self._place(a, ctx), self._place(b, ctx),
                            colors)
        self._hitboxes = {}
        for v in self._stations.values():
            cx, cy = self._place(v, ctx)
            draw_circle(draw, (cx, cy), STATION_RADIUS, fill=ctx.theme.bg,
                        outline=ctx.theme.fg, width=2)
            self._hitboxes[(cx - HIT_PAD, cy - HIT_PAD, cx + HIT_PAD,
                            cy + HIT_PAD)] = v["id"]
        return True

    def _draw_edge(self, draw, p0: tuple[float, float],
                   p1: tuple[float, float], colors: list[str]) -> None:
        """One straight shot between adjacent stations.

        A single-color segment is one line; a shared-track segment draws
        the colors as parallel lines side by side — half and half, never
        striped — each offset perpendicular to the segment.
        """
        if len(colors) == 1:
            draw.line((p0[0], p0[1], p1[0], p1[1]),
                      fill=LINE_COLORS[colors[0]], width=EDGE_WIDTH)
            return
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = -dy / length, dx / length  # perpendicular unit vector
        step = EDGE_WIDTH + 2
        start = -(len(colors) - 1) * step / 2
        for i, color in enumerate(colors):
            offset = start + i * step
            a = (p0[0] + ux * offset, p0[1] + uy * offset)
            b = (p1[0] + ux * offset, p1[1] + uy * offset)
            draw.line((a[0], a[1], b[0], b[1]),
                      fill=LINE_COLORS[color], width=EDGE_WIDTH)

    # --- taps --------------------------------------------------------------

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        # the nearest station center within HIT_PAD wins: downtown
        # stations are closer than a hitbox apart, so overlap order must
        # not decide the trip
        best = None
        bestd = HIT_PAD
        for v in self._stations.values():
            cx, cy = self._place(v, ctx)
            d = math.hypot(cx - x, cy - y)
            if d <= bestd:
                best, bestd = v, d
        if best is not None:
            self._start_trip(best["id"], ctx)
            return True
        return False

    def _start_trip(self, vid: str, ctx: Ctx) -> bool:
        self._abandon()
        data = ctx.config.namespace("boston")
        address = (data.get("address") or "").strip()
        api_key = (data.get("api_key") or "").strip()
        mode = data.get("mode", "transit")
        if mode not in MODES:
            mode = "transit"
        station = self._stations[vid]
        if not address or not api_key:
            missing = "address" if not address else "google api key"
            self._alert = TripAlert(self, station, address, mode, self._seq,
                                    error=f"no {missing} set - add it on the"
                                          f" web page")
        else:
            self._alert = TripAlert(self, station, address, mode,
                                    self._restart(ctx, station, mode))
        ctx.nav.push(self._alert)
        return True

    # --- query lifecycle (background threads -> queue -> main loop) --------

    def _abandon(self) -> None:
        self._seq += 1  # every in-flight result becomes stale
        self._alert = None

    def _note_alert_gone(self, ctx: Ctx) -> None:
        # the bar's [‹ BACK] pops the alert without a callback — detect it
        if self._alert is not None and self._alert not in ctx.nav.stack:
            self._abandon()

    def _restart(self, ctx: Ctx, station: dict, mode: str) -> int:
        """Start a query with the current config; returns its seq."""
        data = ctx.config.namespace("boston")
        address = (data.get("address") or "").strip()
        api_key = (data.get("api_key") or "").strip()
        self._seq += 1
        seq = self._seq
        threading.Thread(target=self._query,
                         args=(seq, station, address, api_key, mode),
                         daemon=True).start()
        return seq

    def _query(self, seq: int, station: dict, address: str, api_key: str,
               mode: str) -> None:
        try:
            trips = self._fetch(address, station["lat"], station["lon"],
                                mode, api_key, time.time())
            self._queue.put((seq, ("ok", trips)))
        except GoogleError as err:
            self._queue.put((seq, ("err", err.message)))
        except Exception:
            log.exception("boston: trip query failed")
            self._queue.put((seq, ("err", "trip query failed")))

    def poll(self, seq: int):
        """Drain the result queue; only a matching seq is returned."""
        while True:
            try:
                got, result = self._queue.get_nowait()
            except queue.Empty:
                return None
            if got == seq:
                return result

    # --- module contract -----------------------------------------------------

    def status_items(self, ctx: Ctx) -> list[BarItem]:
        address = (ctx.config.namespace("boston").get("address") or ""
                   ).strip()
        if not address:
            return [BarItem("no address set")]
        return [BarItem("to " + truncate(ctx.fonts, address, 220,
                                         size=SIZE_FORM))]

    def on_action(self, action_id: str, ctx: Ctx) -> None:
        if action_id == "abandon":
            self._abandon()  # the alert notices the seq moved and pops


class TripAlert:
    """The trip dialog pushed on station tap.

    States: confirm (from/to + cycling mode picker, [cancel] [ok]) —
    computing (the query is in flight; interval=1 re-renders each second
    so the result is picked up promptly) — results (one itinerary at a
    time, scrollable legs, [<] [done] [>]) — error (message, [done]).
    """

    title = "TRIP"

    @property
    def interval(self) -> int:
        """Tick only while a query can still land.

        `confirm` waits on the query that started with the dialog, so a
        result or an error appears without another tap; `results` and
        `error` are static, and re-rendering them once a second would
        repaint an identical frame forever.
        """
        return 1 if self._state in ("confirm", "computing") else 0

    def __init__(self, module: Boston, station: dict, address: str,
                 mode: str, seq: int, error: str | None = None) -> None:
        self._module = module
        self._station = station
        self._address = address
        self._mode = mode       # the picker's current value
        self._query_mode = mode  # the mode the in-flight query uses
        self._seq = seq
        self._state = "error" if error else "confirm"
        self._error = error
        self._pending = None    # result that arrived while confirming
        self._trips = []
        self._index = 0
        self._leg_offset = 0
        self._footer: dict[str, tuple | None] = {}
        self._x_rect: tuple | None = None
        self._mode_rect: tuple | None = None
        self._scroller: dict[str, tuple | None] = {"up": None, "down": None}

    # --- state transitions ---------------------------------------------------

    def _apply_trips(self, trips) -> None:
        if not trips:
            self._fail("no route found to that station")
            return
        self._trips = trips
        self._index = 0
        self._leg_offset = 0
        self._state = "results"

    def _fail(self, message: str) -> None:
        self._state = "error"
        self._error = message

    def _dismiss(self, ctx: Ctx) -> None:
        self._module._abandon()
        ctx.nav.pop()

    def _confirm(self, ctx: Ctx) -> None:
        if self._mode == self._query_mode:
            if self._pending is not None:
                self._apply_trips(self._pending)
            else:
                self._state = "computing"
            return
        # the picker moved off the settings default: query again
        self._pending = None
        self._query_mode = self._mode
        self._seq = self._module._restart(ctx, self._station, self._mode)
        self._state = "computing"

    def _cycle_mode(self) -> None:
        self._mode = MODES[(MODES.index(self._mode) + 1) % len(MODES)]

    # --- protocol -------------------------------------------------------------

    def render(self, draw, ctx: Ctx) -> bool:
        if self._seq != self._module._seq:  # abandoned from the web side
            ctx.nav.pop()
            return True
        if self._state in ("confirm", "computing"):
            result = self._module.poll(self._seq)
            if result is not None:
                if result[0] == "ok":
                    if self._state == "confirm":
                        self._pending = result[1]  # reveal on [ok]
                    else:
                        self._apply_trips(result[1])
                else:
                    self._fail(result[1])
        draw.rectangle(ctx.content, fill=ctx.theme.bg)
        self._footer = {}
        self._mode_rect = None
        self._scroller = {"up": None, "down": None}
        self._draw_header(draw, ctx)
        if self._state == "confirm":
            self._draw_confirm(draw, ctx)
        elif self._state == "computing":
            self._draw_computing(draw, ctx)
        elif self._state == "results":
            self._draw_results(draw, ctx)
        else:
            self._draw_error(draw, ctx)
        self._draw_footer(draw, ctx)
        return True

    def _draw_header(self, draw, ctx: Ctx) -> None:
        theme = ctx.theme
        fonts = ctx.fonts
        x0, y0, x1, _y1 = ctx.content
        title = {"confirm": "CALCULATE TRIP?", "computing": "COMPUTING...",
                 "results": f"TRIP {self._index + 1}/{len(self._trips)}",
                 "error": "TRIP"}[self._state]
        fonts.draw_text(draw, (x0 + 12,
                               text_y(fonts, title, y0, y0 + HEADER_H,
                                      size=SIZE_FORM)),
                        title, "regular", SIZE_FORM, theme.fg)
        self._x_rect = draw_button_auto(draw, x1 - 12, y0 + 4, HEADER_H - 8,
                                        "X", fonts, theme, size=SIZE_FORM,
                                        min_width=40)
        draw.line((x0, y0 + HEADER_H, x1, y0 + HEADER_H),
                  fill=theme.border)

    def _row(self, draw, ctx: Ctx, top: int, text: str, color) -> None:
        x0, _y0, x1, _y1 = ctx.content
        shown = truncate(ctx.fonts, text, x1 - x0 - 24, size=SIZE_FORM)
        ctx.fonts.draw_text(draw, (x0 + 12,
                                   text_y(ctx.fonts, shown, top, top + ROW_H,
                                          size=SIZE_FORM)),
                            shown, "regular", SIZE_FORM, color)

    def _body_top(self, ctx: Ctx) -> int:
        return ctx.content[1] + HEADER_H + BODY_MARGIN

    def _draw_confirm(self, draw, ctx: Ctx) -> None:
        theme = ctx.theme
        top = self._body_top(ctx)
        self._row(draw, ctx, top, f"from  {self._address}", theme.fg)
        top += ROW_H
        self._row(draw, ctx, top, f"to    {self._station['name'].upper()}",
                  theme.fg)
        top += ROW_H
        self._row(draw, ctx, top, "mode", theme.dim)
        x1 = ctx.content[2]
        self._mode_rect = draw_button_auto(
            draw, x1 - 12, top + 4, ROW_H - 8,
            f"{self._mode} [next ›]", ctx.fonts, theme, size=SIZE_FORM)
        top += ROW_H
        self._row(draw, ctx, top, "leaving now", theme.dim)

    def _draw_computing(self, draw, ctx: Ctx) -> None:
        theme = ctx.theme
        top = self._body_top(ctx)
        self._row(draw, ctx, top, "from  " + self._address, theme.dim)
        top += ROW_H
        self._row(draw, ctx, top,
                  "to    " + self._station["name"].upper(), theme.dim)
        top += ROW_H
        self._row(draw, ctx, top, "asking google maps...", theme.fg)

    def _leg_rows(self, trip) -> list[str]:
        """Every row of the scrollable itinerary body.

        A transit ride is two rows (times/headsign, then the stops you
        board and get off at); a street leg is a summary row plus one
        row per street-by-street instruction.
        """
        rows = []
        for leg in trip.legs:
            if leg.mode == "transit":
                parts = [fmt_clock(leg.start), leg.title.upper()]
                if leg.detail:
                    parts.append(leg.detail.upper())
                rows.append(" ".join(parts))
                stops = []
                if leg.board:
                    stops.append(f"board {leg.board}")
                if leg.alight:
                    stops.append(f"off {leg.alight}")
                if stops:
                    rows.append("  " + " · ".join(stops).upper())
            else:
                rows.append(f"{leg.title.upper()} {leg.detail.upper()}")
                for step in leg.steps:
                    rows.append("  " + step.upper())
        return rows

    def _draw_results(self, draw, ctx: Ctx) -> None:
        theme = ctx.theme
        x0, _y0, x1, y1 = ctx.content
        trip = self._trips[self._index]
        top = self._body_top(ctx)
        summary = []
        if trip.depart:
            summary.append(f"leave {fmt_clock(trip.depart)}")
        if trip.arrive:
            summary.append(f"arrive {fmt_clock(trip.arrive)}")
        summary.append(f"{fmt_minutes(trip.duration)} total")
        self._row(draw, ctx, top, " · ".join(summary), theme.fg)
        legs_top = top + ROW_H + BODY_MARGIN
        scroller_strip = (x0, y1 - FOOTER_H - SCROLLER_H, x1, y1 - FOOTER_H)
        per_page = max(1, (scroller_strip[1] - legs_top) // ROW_H)
        rows = self._leg_rows(trip)
        self._leg_offset = min(max(self._leg_offset, 0),
                               max(len(rows) - per_page, 0))
        for i, text in enumerate(rows[self._leg_offset:
                                      self._leg_offset + per_page]):
            self._row(draw, ctx, legs_top + i * ROW_H, text, theme.fg)
        self._scroller = draw_scroller(
            draw, scroller_strip, self._leg_offset, per_page, len(rows),
            ctx.fonts, theme)

    def _draw_error(self, draw, ctx: Ctx) -> None:
        theme = ctx.theme
        top = self._body_top(ctx)
        lines = textwrap.wrap(self._error or "something went wrong", 58)
        for line in lines:
            self._row(draw, ctx, top, line, theme.fg)
            top += ROW_H

    def _draw_footer(self, draw, ctx: Ctx) -> None:
        theme = ctx.theme
        fonts = ctx.fonts
        x0, _y0, x1, y1 = ctx.content
        strip_top = y1 - FOOTER_H
        draw.line((x0, strip_top, x1, strip_top), fill=theme.border)
        if self._state == "confirm":
            labels = [("cancel", True), ("ok", True)]
        elif self._state == "computing":
            labels = [("cancel", True)]
        elif self._state == "results":
            n = len(self._trips)
            labels = [("<", self._index > 0), ("done", True),
                      (">", self._index < n - 1)]
        else:
            labels = [("done", True)]
        width, height, gap = 130, FOOTER_H - 8, 16
        total = len(labels) * width + (len(labels) - 1) * gap
        cursor = x0 + (x1 - x0 - total) / 2
        for action, enabled in labels:
            rect = (cursor, strip_top + 4, cursor + width, strip_top + height)
            draw_button(draw, rect, action, fonts, theme, size=SIZE_FORM,
                        enabled=enabled)
            # disabled keys stay present as None: grey and inert at the ends
            self._footer[action] = rect if enabled else None
            cursor += width + gap

    def on_tap(self, x: int, y: int, ctx: Ctx) -> bool:
        if _inside(self._x_rect, x, y):
            self._dismiss(ctx)
            return True
        if self._state == "confirm" and _inside(self._mode_rect, x, y):
            self._cycle_mode()
            return True
        for action, rect in self._footer.items():
            if _inside(rect, x, y):
                if action == "ok":
                    self._confirm(ctx)
                elif action == "cancel" or action == "done":
                    self._dismiss(ctx)
                elif action == "<":
                    self._index -= 1
                    self._leg_offset = 0
                elif action == ">":
                    self._index += 1
                    self._leg_offset = 0
                return True
        if self._state == "results":
            for direction, rect in self._scroller.items():
                if _inside(rect, x, y):
                    self._leg_offset += 1 if direction == "down" else -1
                    return True
        return False


MODULE = Boston()
