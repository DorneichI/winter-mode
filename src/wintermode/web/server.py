"""The web companion: a tiny REST server + one terminal-styled page.

No live mode, no WebSocket, no polling: the page is the settings grid
in a browser — click into a module, edit its config, trigger its
actions.  Handlers never draw and never touch the display: they read
config under its lock, and actions are expressed by enqueueing
(module_id, action_id) for the main loop to execute on its thread.
Idle cost is ~zero — the server thread sits in accept().
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from wintermode import __version__, device, schema
from wintermode.fonts import FONTS_DIR
from wintermode.net import DEFAULT_WEB_PORT, ipv4, web_url
from wintermode.theme import effective_theme

log = logging.getLogger(__name__)

DEFAULT_PORT = DEFAULT_WEB_PORT
STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024  # nothing this UI sends is bigger; cap the read

# a constant name -> path map: user input is looked up, never joined
# into a filesystem path (keeps py/path-injection taint clean)
FONT_FILES = {
    "3270-Regular.ttf": FONTS_DIR / "3270-Regular.ttf",
    "3270SemiCondensed-Regular.ttf": FONTS_DIR / "3270SemiCondensed-Regular.ttf",
}

# the boston map graph, edited by the /map arrangement page
GRAPH_PATH = Path(__file__).resolve().parent.parent / "modules" / "boston" / \
    "graph.json"


def _theme_tokens(theme) -> dict[str, str]:
    def rgb(color) -> str:
        return f"rgb({color[0]},{color[1]},{color[2]})"

    return {name: rgb(getattr(theme, name))
            for name in ("bg", "fg", "accent", "dim", "border")}


class WebServer:
    def __init__(self, config, registry, actions, port: int = DEFAULT_PORT) -> None:
        self.config = config
        self.registry = registry
        self.actions = actions  # queue.Queue drained by the main loop
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        config = self.config
        registry = self.registry
        actions = self.actions
        port = self.port

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep the log quiet
                pass

            # -- plumbing ----------------------------------------------------
            def _send(self, code: int, payload, ctype: str = "application/json"):
                body = payload if isinstance(payload, bytes) \
                    else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json_body(self):
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return None
                if not length:
                    return {}
                if length > MAX_BODY:
                    return None
                try:
                    data = json.loads(self.rfile.read(length))
                except ValueError:
                    return None
                return data if isinstance(data, dict) else None

            def _module(self, module_id: str):
                module = registry.get(module_id)
                if module is None:
                    self._send(404, {"error": f"unknown module {module_id!r}"})
                    return None
                return module

            # -- GET ---------------------------------------------------------
            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/":
                    page = (STATIC_DIR / "index.html").read_bytes()
                    return self._send(200, page, "text/html; charset=utf-8")
                if path == "/map":
                    page = (STATIC_DIR / "map.html").read_bytes()
                    return self._send(200, page, "text/html; charset=utf-8")
                if path.startswith("/font/"):
                    name = path[len("/font/"):]
                    font_path = FONT_FILES.get(name)
                    if font_path is not None:
                        return self._send(200, font_path.read_bytes(),
                                          "font/ttf")
                    return self._send(404, {"error": "unknown font"})
                if path == "/api/boston/graph":
                    try:
                        data = json.loads(GRAPH_PATH.read_text())
                    except (OSError, ValueError):
                        return self._send(500, {"error": "unreadable graph"})
                    return self._send(200, data)
                if path == "/api/modules":
                    payload = [{
                        "id": module.id, "title": module.title,
                        "interval": module.interval, "enabled": True,
                        "actions": module.actions,
                        "schema": module.config_schema or {},
                    } for module in registry.home_order()]
                    return self._send(200, payload)
                if path == "/api/device":
                    return self._send(200, self._device_payload())
                parts = self._split(path, "/api/modules/", 2)
                if parts and parts[1] == "config":
                    module = self._module(parts[0])
                    if module is None:
                        return
                    spec = module.config_schema or {}
                    values = dict(config.data.get(module.id, {}))
                    # write-only fields (api keys) leave the panel, not
                    # the browser: a set value reads back as empty, and
                    # the masked list tells the page it can be reset
                    masked = [key for key, field in spec.items()
                              if field.get("write_only") and values.get(key)]
                    for key in masked:
                        values[key] = ""
                    return self._send(200, {
                        "schema": spec,
                        "values": values,
                        "masked": masked,
                    })
                self._send(404, {"error": "not found"})

            # -- PUT ---------------------------------------------------------
            def do_PUT(self) -> None:
                path = urlparse(self.path).path
                body = self._json_body()
                if body is None:
                    return self._send(400, {"error": "expected a JSON object"})
                if path == "/api/boston/graph":
                    return self._put_graph(body)
                parts = self._split(path, "/api/modules/", 2)
                if parts and parts[1] == "config":
                    module = self._module(parts[0])
                    if module is None:
                        return
                    try:
                        schema.validate_strict(module.config_schema or {}, body)
                        current = config.data.get(module.id, {})
                        if not isinstance(current, dict):
                            current = {}
                        valid = schema.validate(module.config_schema or {},
                                                {**current, **body})
                    except ValueError as error:
                        return self._send(400, {"error": str(error)})
                    except (TypeError, KeyError) as error:
                        # null for an int, a choice spec with no options:
                        # the body is bad, the handler must still answer
                        return self._send(400, {"error": f"invalid value: {error}"})
                    config.update_module(module.id, valid)
                    return self._send(200, {"values": valid})
                group = self._split(path, "/api/device/", 1)
                if group:
                    return self._put_device(group[0], body)
                self._send(404, {"error": "not found"})

            # -- POST --------------------------------------------------------
            def do_POST(self) -> None:
                path = urlparse(self.path).path
                parts = self._split(path, "/api/modules/", 3)
                if parts and parts[1] == "actions":
                    module = self._module(parts[0])
                    if module is None:
                        return
                    action_id = parts[2]
                    if not any(a["id"] == action_id for a in module.actions):
                        return self._send(400, {"error": "unknown action"})
                    actions.put((module.id, action_id))  # main loop executes
                    return self._send(200, {"ok": True})
                self._send(404, {"error": "not found"})

            # -- payloads -----------------------------------------------------
            @staticmethod
            def _split(path: str, prefix: str, n: int):
                if not path.startswith(prefix):
                    return None
                parts = path[len(prefix):].split("/")
                return parts if len(parts) == n else None

            def _device_payload(self) -> dict:
                theme = effective_theme(config, time.time())
                ip = ipv4()  # one UDP socket for the whole payload
                return {
                    "theme": {"name": theme.name},
                    "tokens": _theme_tokens(theme),
                    "network": {
                        "hostname": socket.gethostname(),
                        "ipv4": ip,
                        "web_url": web_url(port),
                    },
                    "version": __version__,
                    "groups": [
                        {"id": group.id, "title": group.title,
                         "schema": group.schema, "values": group.read()}
                        for group in device.groups(config, registry)
                    ],
                }

            def _put_graph(self, body: dict) -> None:
                """Move boston stations: apply {vertices: [{id, x, y}]} to
                graph.json and tell the module to re-read it."""
                moved = body.get("vertices")
                if not isinstance(moved, list) or not moved:
                    return self._send(400, {"error": "vertices must be a list"})
                try:
                    graph = json.loads(GRAPH_PATH.read_text())
                except (OSError, ValueError):
                    return self._send(500, {"error": "unreadable graph"})
                known = {v["id"]: v for v in graph.get("vertices", [])}
                try:
                    for entry in moved:
                        vid = entry.get("id")
                        if vid not in known:
                            return self._send(
                                400, {"error": f"unknown station {vid!r}"})
                        x = float(entry.get("x"))
                        y = float(entry.get("y"))
                        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                            return self._send(
                                400, {"error": "x/y must be within 0..1"})
                        known[vid]["x"] = x
                        known[vid]["y"] = y
                except (TypeError, ValueError):
                    return self._send(400, {"error": "invalid station entry"})
                try:
                    GRAPH_PATH.write_text(json.dumps(graph, indent=2) + "\n")
                except OSError:
                    return self._send(500, {"error": "could not write graph"})
                actions.put(("boston", "reload"))  # main loop re-reads it
                return self._send(200, {"ok": True})

            def _put_device(self, group_id: str, body: dict) -> None:
                group = device.group_by_id(config, registry, group_id)
                if group is None:
                    return self._send(404, {"error": "not found"})
                try:
                    group.apply(body)
                except ValueError as error:
                    return self._send(400, {"error": str(error)})
                except (TypeError, KeyError, AttributeError) as error:
                    # a body the DSL cannot even look at (null for an int,
                    # a list for a group) is still the client's fault
                    return self._send(400, {"error": f"invalid value: {error}"})
                return self._send(200, {"ok": True})

        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        except OSError:
            log.warning("web: port %s unavailable — web UI disabled", port)
            return
        # port 0 means "any free port": report the one we actually got,
        # so the panel and the REST payload advertise a live URL
        self.port = port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever,
                         name="wintermode-web", daemon=True).start()
        log.info("web: %s/", web_url(port))

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
