"""Shared plumbing for the boot updater (deploy/update.py, healthcheck.py).

HARD RULES — the whole design rests on these:

- stdlib ONLY, and never import the wintermode package: this runs with
  the system /usr/bin/python3 before the app starts, on a checkout that
  may be broken or mid-update.  It must not depend on the code it is
  about to replace, or on the venv.
- subprocess with argv lists only — never a shell command line — and
  always with a timeout: a hung git or pip must cost a bounded boot
  delay, never a wedged Pi.
- print/log to stdout: systemd captures it into journald.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path("/opt/winter-mode")
CONFIG = Path("/etc/wintermode/config.json")
TARGET_REF = "origin/main"
VERSION_NAME = "version"       # stamped next to the config file
STATE_NAME = "update-state.json"

FETCH_TIMEOUT = 60    # the whole boot stalls on this; a Pi on wifi is slow
GIT_TIMEOUT = 15
RESET_TIMEOUT = 60
PIP_TIMEOUT = 900     # an ertftm070 recompile on a Zero W is minutes
HTTP_TIMEOUT = 2.0

PIP_ARGS = ["install", "-e", ".", "--only-binary", ":all:",
            "--no-binary", "ertftm070", "--disable-pip-version-check",
            "--no-input"]

SHA_RE = re.compile(r"[0-9a-f]{7,40}")

log = logging.getLogger("updater")

# state keys and their sanitizing defaults: a corrupt file must read as
# "nothing happened yet", never as an instruction
STATE_DEFAULTS = {
    "lkg": None,          # last known good — recorded BEFORE every move
    "hold": None,         # pinned here by a rollback; never fetched
    "last_sync": None,    # the commit whose deps the venv matches
    "pending": None,      # deployed but not yet confirmed by a healthcheck
    "bad": None,          # failed its healthcheck; never re-applied
    "fails": 0,           # consecutive unhealthy boots
    "venv_dirty": False,  # a venv resync is still owed (pip failed)
}


def setup_logging() -> None:
    """INFO to stdout -> journald.  A no-op when a handler already
    exists (pytest's capture owns the root logger in tests), so repeated
    main() calls never stack or clobber handlers."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s updater: %(message)s",
                        stream=sys.stdout)


def git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str | None:
    """Run git in `repo`; stripped stdout, or None after logging stderr.

    One call site for every git invocation: the timeout and the "no
    shell" rule cannot be forgotten anywhere.
    """
    command = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        log.warning("git %s timed out after %ss", args[0], timeout)
        return None
    except OSError:
        log.warning("git is not available")
        return None
    if result.returncode != 0:
        log.warning("git %s failed: %s", " ".join(args),
                    result.stderr.strip()[:200])
        return None
    return result.stdout.strip()


def head_sha(repo: Path) -> str | None:
    value = git(repo, "rev-parse", "HEAD")
    if value and SHA_RE.fullmatch(value):
        return value
    log.warning("rev-parse HEAD returned something odd: %r", value)
    return None


def describe(repo: Path) -> str:
    """`git describe --tags --always` — a bare short sha until tags exist."""
    value = git(repo, "describe", "--tags", "--always") or "unknown"
    return value if value.isprintable() and len(value) <= 64 else "unknown"


def diff_touches(repo: Path, old: str, new: str, path: str) -> bool:
    """Did `path` change between `old` and `new`?  Fail toward True.

    `git diff --quiet` prints nothing; only the exit code answers
    (0 = identical, 1 = different, anything else = error -> "resync").
    """
    command = ["git", "-C", str(repo), "diff", "--quiet", old, new,
               "--", path]
    try:
        result = subprocess.run(command, capture_output=True,
                                timeout=GIT_TIMEOUT, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return True
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    log.warning("git diff --quiet %s..%s -- %s exited %s", old, new, path,
                result.returncode)
    return True


def load_state(config: Path) -> dict:
    """The state file next to the config, sanitized key by key.

    A corrupt or non-dict file is treated as `{}` (replaced on the next
    save) and never raises — a broken state file must not brick a boot.
    """
    path = Path(config).parent / STATE_NAME
    state = dict(STATE_DEFAULTS)
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return state
    if not isinstance(raw, dict):
        return state
    for key, default in STATE_DEFAULTS.items():
        value = raw.get(key)
        if default is None:
            state[key] = value if isinstance(value, str) and \
                SHA_RE.fullmatch(value) else None
        elif isinstance(default, bool):
            state[key] = bool(value)
        else:
            state[key] = value if isinstance(value, int) else 0
    return state


def save_state(config: Path, state: dict) -> bool:
    """Atomic write (tmp + os.replace — the write_atomic pattern, which
    cannot be imported here) next to the config."""
    path = Path(config).parent / STATE_NAME
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.replace(path)
    except OSError:
        log.warning("could not write %s (read-only?)", path)
        return False
    return True


def read_policy(config: Path) -> bool:
    """The "updates" root key, read RAW from config.json.

    The updater cannot import the app, so this must agree with
    UPDATES_SCHEMA's default by hand: missing file, unparsable file, or
    a non-object "updates" all mean auto-update ON.
    """
    try:
        raw = json.loads(Path(config).read_text())
    except (OSError, ValueError):
        return True
    if not isinstance(raw, dict):
        return True
    namespace = raw.get("updates")
    if not isinstance(namespace, dict):
        return True
    return coerce_bool(namespace.get("auto", True))


def coerce_bool(value, default: bool = True) -> bool:
    """Mirror schema.coerce_bool: hand-edits like "off" mean off."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off", ""):
            return False
        return default
    if isinstance(value, (bool, int)):
        return bool(value)
    return default


def version_file(config: Path) -> Path:
    return Path(config).parent / VERSION_NAME


def write_version(config: Path, repo: Path) -> bool:
    """Stamp `git describe --tags --always` next to the config."""
    try:
        text = describe(repo) + "\n"
        tmp = version_file(config).with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(version_file(config))
    except OSError:
        log.warning("could not write the version stamp (read-only?)")
        return False
    return True


def reset_hard(repo: Path, sha: str) -> bool:
    return git(repo, "reset", "--hard", sha, timeout=RESET_TIMEOUT) is not None


def tree_dirty(repo: Path) -> bool:
    """Any uncommitted change in the checkout (about to be discarded)."""
    return git(repo, "status", "--porcelain") not in (None, "")


def sync_venv(repo: Path, timeout: int = PIP_TIMEOUT) -> bool:
    """Re-run the Pi's editable install: the checkout IS the install.

    Only runs when pyproject.toml changed (or a previous sync failed),
    so an ertftm070 C recompile is not a boot-time routine.  `build/` is
    a stale artifact of the old non-editable installs and is removed.
    """
    shutil.rmtree(repo / "build", ignore_errors=True)
    pip = repo / ".venv" / "bin" / "pip"
    if not pip.exists():
        log.warning("%s missing — cannot resync the venv", pip)
        return False
    try:
        result = subprocess.run(
            [str(pip), *PIP_ARGS], cwd=repo, capture_output=True,
            text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        log.warning("pip timed out after %ss", timeout)
        return False
    except OSError:
        log.warning("pip is not runnable")
        return False
    if result.returncode != 0:
        log.warning("pip failed (rc %s):\n%s", result.returncode,
                    "\n".join(result.stdout.splitlines()[-20:]))
        return False
    log.info("venv resynced")
    return True


def probe_http(url: str, timeout: float = HTTP_TIMEOUT) -> dict | None:
    """One GET; a parsed JSON object, or None for any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read(64 * 1024))
    except Exception:  # noqa: BLE001 - any failure is "not healthy"
        return None
    return payload if isinstance(payload, dict) else None
