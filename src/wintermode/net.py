"""Small network helpers shared by the settings module and the web server."""

from __future__ import annotations

import socket


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
