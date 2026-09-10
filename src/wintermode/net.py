"""Small network helpers shared by the settings module and the web server."""

from __future__ import annotations

import socket

DEFAULT_WEB_PORT = 8080


def ipv4() -> str:
    """This host's outbound IPv4 (the LAN address the web UI lives on)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "unknown"


def web_url(port: int | None = DEFAULT_WEB_PORT) -> str:
    """The URL the web UI is reachable at — the ONE place it is formatted.

    `port` is the port the server actually bound (None while it is not
    running), so the panel and the REST payload cannot disagree.
    """
    return f"http://{ipv4()}:{port or DEFAULT_WEB_PORT}"
