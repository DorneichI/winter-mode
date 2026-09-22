"""The version the panel shows: what is deployed, not what was installed.

`importlib.metadata` reports the wheel/sdist version, which for an
editable install is frozen at "0.1.0" forever.  The real answer is
stamped by the boot updater next to the config (`/etc/wintermode/version`,
`git describe --tags --always`); this is the only reader.
"""

from __future__ import annotations

from pathlib import Path

from wintermode import __version__

VERSION_FILENAME = "version"
MAX_LEN = 64


def version_path(config_path) -> Path:
    return Path(config_path).parent / VERSION_FILENAME


def read_deployed_version(config_path) -> str:
    """The updater's stamp next to the config, or the installed version.

    Any OSError (missing file, unreadable) and any garbage that could
    not come from `git describe` falls back to `__version__` — the
    splash must never crash or show junk because of a stray file.
    """
    try:
        text = version_path(config_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        # missing, unreadable, or not text at all (a binary file, say)
        return __version__
    if not text or len(text) > MAX_LEN or not text.isprintable():
        return __version__
    return text
