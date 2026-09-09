"""winter-mode — a HomePod-style kitchen dashboard for the ER-TFTM070-4."""

try:  # installed package: version comes from the distribution metadata
    from importlib.metadata import version as _version

    __version__ = _version("winter-mode")
except Exception:  # pragma: no cover - running from a source checkout
    __version__ = "0.1.0"
