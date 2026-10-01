"""Post-boot health check: confirm the deployed commit, or roll back.

Runs as the app unit's ExecStartPost, with the system python.  The web
server only binds once the first frame has rendered, so "GET
/api/device serves the wintermode payload" is the process-level health
signal: a commit whose first render raises never answers the probe.
The payload carries an identity marker (`"app": "wintermode"`) — a
stray service squatting :8080 must never confirm a deploy.

- Healthy: the deployed commit is confirmed (hold/pending cleared).
- Unhealthy: HEAD is reset to last-known-good (with a venv resync if
  pyproject differs), the failed commit is marked `bad` so the updater
  never re-applies it, and we exit 1 — the unit fails and
  `Restart=always` boots the panel on the old code.  No polkit, no
  systemctl from here: systemd does the restarting.
- When a restart could change nothing (no last-known-good recorded, or
  the last-known-good itself is unhealthy), we exit 0 instead: an
  ExecStartPost failure would make systemd kill and restart the panel
  forever at ~25 s per cycle.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import updatelib as lib


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="health-check the running winter-mode, roll back on"
                    " failure")
    parser.add_argument("--repo", type=Path, default=lib.REPO)
    parser.add_argument("--config", type=Path, default=lib.CONFIG)
    parser.add_argument("--url", default="http://127.0.0.1:8080/api/device")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--rollback-after", type=int, default=1,
                        help="roll back only after this many consecutive"
                             " unhealthy probes (guard against false"
                             " positives)")
    return parser.parse_args(argv)


def wait_healthy(url: str, timeout: float, interval: float,
                 probe=None, sleep=time.sleep) -> dict | None:
    """Poll until one 200 JSON object, or the monotonic deadline.

    `probe` resolves at call time (not as a bound default) so tests can
    monkeypatch lib.probe_http.
    """
    if probe is None:
        probe = lib.probe_http
    deadline = time.monotonic() + timeout
    while True:
        payload = probe(url)
        if payload is not None:
            return payload
        if time.monotonic() + interval > deadline:
            return None
        sleep(interval)


def on_healthy(repo: Path, config: Path, state: dict, payload: dict) -> int:
    head = lib.head_sha(repo)
    if state["hold"] == head or state["pending"] == head:
        lib.log.info("deployed commit %s confirmed healthy", head)
        state.update(hold=None, pending=None)
    # any healthy probe resets the streak — a past transient failure must
    # not count toward the next deploy's rollback threshold
    state["fails"] = 0
    # the failed commit now boots fine (e.g. it only failed offline):
    # un-bad it.  Never clear `bad` while running something else — the
    # updater clears it only when main moves past it, otherwise the
    # broken commit would be re-applied every boot.
    if state["bad"] and state["bad"] == head:
        lib.log.info("the previously failed commit %s is healthy", head)
        state["bad"] = None
    served = payload.get("version")
    if served and lib.describe(repo) not in (served, "unknown"):
        # log only: the stamp file may be unwritable (the app then falls
        # back to __version__) — a stale display string must not roll
        # anything back
        lib.log.warning("web serves version %r but HEAD describes %r",
                        served, lib.describe(repo))
    lib.write_version(config, repo)
    lib.save_state(config, state)
    return 0


def rollback(repo: Path, config: Path, state: dict, head: str,
             rollback_after: int) -> int:
    """Unhealthy.  Decide: roll back, hold off, or leave it alone."""
    lkg = state["lkg"]
    if lkg is None:
        # exit 0, not 1: an ExecStartPost failure would kill the panel
        # and restart it, and no LKG means the restart changes nothing —
        # the same code would probe the same way, forever
        lib.log.warning("no last-known-good recorded — leaving the"
                        " checkout alone")
        lib.write_version(config, repo)
        lib.save_state(config, state)
        return 0
    if head == lkg:
        # LKG itself is broken: rolling back changes nothing.  Unpin so
        # the next boot may fetch fresh main instead of holding forever
        # — this needs a human.  Keep `bad`: the updater must NOT
        # re-apply it while running something else (the loop rule), and
        # its guard re-pins the hold next boot anyway.  Exit 0 for the
        # same reason as above.
        lib.log.warning("last-known-good %s is unhealthy too — a human is"
                        " needed", lkg)
        state.update(hold=None, pending=None, fails=0)
        lib.write_version(config, repo)
        lib.save_state(config, state)
        return 0
    state["fails"] += 1
    if state["fails"] < rollback_after:
        lib.log.warning("unhealthy boot %s/%s — not rolling back yet",
                        state["fails"], rollback_after)
        lib.save_state(config, state)
        return 1
    lib.log.info("unhealthy — rolling back to last-known-good %s", lkg)
    if not lib.reset_hard(repo, lkg):
        lib.log.warning("rollback reset failed")
        lib.save_state(config, state)
        return 1
    if lib.diff_touches(repo, head, lkg, "pyproject.toml"):
        if lib.sync_venv(repo):
            state["last_sync"] = lkg
            state["venv_dirty"] = False
        else:
            state["venv_dirty"] = True
    state.update(hold=lkg, bad=head, pending=None, fails=0)
    lib.write_version(config, repo)
    lib.save_state(config, state)
    lib.log.info("rolled back to %s; exiting 1 so Restart=always reboots"
                 " the panel", lkg)
    return 1


def main(argv=None) -> int:
    lib.setup_logging()
    args = parse_args(argv)
    state = lib.load_state(args.config)
    payload = wait_healthy(args.url, args.timeout, args.interval)
    head = lib.head_sha(args.repo)
    if payload is not None and payload.get("app") == "wintermode":
        return on_healthy(args.repo, args.config, state, payload)
    if payload is not None:
        # a 200 JSON object that is not wintermode (a stray service on
        # :8080) must never confirm a deploy
        lib.log.warning("a non-wintermode service answers on %s", args.url)
    if head is None:
        return 1
    return rollback(args.repo, args.config, state, head, args.rollback_after)


if __name__ == "__main__":
    raise SystemExit(main())
