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

from wintermode import __version__, schema
from wintermode.config import DISPLAY_SCHEMA, THEME_SCHEMA
from wintermode.fonts import FONTS_DIR
from wintermode.net import ipv4
from wintermode.theme import effective_theme

log = logging.getLogger(__name__)

DEFAULT_PORT = 8080
STATIC_DIR = Path(__file__).parent / "static"

FONT_FILES = {"3270-Regular.ttf", "3270SemiCondensed-Regular.ttf"}


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
                length = int(self.headers.get("Content-Length") or 0)
                if not length:
                    return {}
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
                if path.startswith("/font/"):
                    name = path[len("/font/"):]
                    if name in FONT_FILES:
                        return self._send(200, (FONTS_DIR / name).read_bytes(),
                                          "font/ttf")
                    return self._send(404, {"error": "unknown font"})
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
                    return self._send(200, {
                        "schema": module.config_schema or {},
                        "values": config.data.get(module.id, {}),
                    })
                self._send(404, {"error": "not found"})

            # -- PUT ---------------------------------------------------------
            def do_PUT(self) -> None:
                path = urlparse(self.path).path
                body = self._json_body()
                if body is None:
                    return self._send(400, {"error": "expected a JSON object"})
                parts = self._split(path, "/api/modules/", 2)
                if parts and parts[1] == "config":
                    module = self._module(parts[0])
                    if module is None:
                        return
                    try:
                        schema.validate_strict(module.config_schema or {}, body)
                        merged = {**config.data.get(module.id, {}), **body}
                        valid = schema.validate(module.config_schema or {},
                                                merged)
                    except ValueError as error:
                        return self._send(400, {"error": str(error)})
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
                return {
                    "theme": {"name": theme.name},
                    "tokens": _theme_tokens(theme),
                    "network": {
                        "hostname": socket.gethostname(),
                        "ipv4": ipv4(),
                        "web_url": f"http://{ipv4()}:{port}",
                    },
                    "version": __version__,
                    "groups": [
                        {"id": "theme", "title": "THEME",
                         "schema": self._theme_schema(),
                         "values": self._theme_values()},
                        {"id": "display", "title": "DISPLAY",
                         "schema": DISPLAY_SCHEMA,
                         "values": config.data.get("display", {})},
                        {"id": "statusbar", "title": "STATUS BAR",
                         "schema": self._statusbar_schema(),
                         "values": self._statusbar_values()},
                    ],
                }

            def _theme_schema(self) -> dict:
                return {
                    **THEME_SCHEMA,
                    "light_from": {"type": "time", "title": "Light from",
                                   "default": "07:00",
                                   "visible_if": {"field": "theme",
                                                  "equals": "auto"}},
                    "light_to": {"type": "time", "title": "Light to",
                                 "default": "19:00",
                                 "visible_if": {"field": "theme",
                                                "equals": "auto"}},
                }

            def _theme_values(self) -> dict:
                return {"theme": config.data["theme"],
                        "light_from": config.data["display"]["light_from"],
                        "light_to": config.data["display"]["light_to"]}

            def _statusbar_schema(self) -> dict:
                schema = {
                    module.id: {"type": "bool",
                                "title": module.title + " bar",
                                "default": True}
                    for module in registry.home_order()
                }
                schema["rotate_seconds"] = {
                    "type": "int", "title": "Rotate every (s)",
                    "min": 0, "max": 3600, "default": 10,
                }
                return schema

            def _statusbar_values(self) -> dict:
                values = {
                    module.id: config.data["statusbar"].get(module.id, True)
                    for module in registry.home_order()
                }
                values["rotate_seconds"] = config.data["statusbar_rotate"]
                return values

            def _put_device(self, group: str, body: dict) -> None:
                try:
                    if group == "theme":
                        schema.validate_strict(self._theme_schema(), body)
                        config.update({
                            "theme": body.get("theme", config.data["theme"]),
                            "display": {
                                "light_from": body.get(
                                    "light_from",
                                    config.data["display"]["light_from"]),
                                "light_to": body.get(
                                    "light_to",
                                    config.data["display"]["light_to"]),
                            },
                        })
                    elif group == "display":
                        schema.validate_strict(DISPLAY_SCHEMA, body)
                        config.update({"display": {
                            **config.data["display"], **body}})
                    elif group == "statusbar":
                        schema.validate_strict(self._statusbar_schema(), body)
                        statusbar = {
                            key: value for key, value in body.items()
                            if key != "rotate_seconds"
                        }
                        config.update({"statusbar": statusbar,
                                       "statusbar_rotate": body.get(
                                           "rotate_seconds",
                                           config.data["statusbar_rotate"])})
                    else:
                        return self._send(404, {"error": "not found"})
                except ValueError as error:
                    return self._send(400, {"error": str(error)})
                return self._send(200, {"ok": True})

        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        except OSError:
            log.warning("web: port %s unavailable — web UI disabled", port)
            return
        threading.Thread(target=self._httpd.serve_forever,
                         name="wintermode-web", daemon=True).start()
        log.info("web: http://%s:%s/", ipv4(), port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
