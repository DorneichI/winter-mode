"""The boot updater: bring /opt/winter-mode to the newest commit.

Runs as a oneshot systemd unit before the dashboard, with the system
python (`/usr/bin/python3`).  All imports happen at module top and every
git/pip call goes through updatelib — a `reset --hard` rewrites this
file mid-run, but Python has already loaded it, and the venv is not
touched for importing.

Fail-open everywhere: a failed fetch or a missing origin runs whatever
is already checked out.  Exit 1 only when policy is on and the checkout
could not be brought to the target (red in `systemctl status`, but the
dashboard still starts — the app unit orders after this one, it does
not require it).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import updatelib as lib

# import anything else only above this line — see the module docstring


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="bring the winter-mode checkout to origin/main")
    parser.add_argument("--repo", type=Path, default=lib.REPO)
    parser.add_argument("--config", type=Path, default=lib.CONFIG)
    return parser.parse_args(argv)


def still_pending(repo: Path, state: dict) -> str | None:
    """The commit a previous boot deployed but no healthcheck confirmed —
    the backstop for systemd versions that do not restart on
    ExecStartPost failure."""
    pending, lkg = state["pending"], state["lkg"]
    current = lib.head_sha(repo)
    if pending and lkg and pending == current and lkg != current:
        return lkg
    return None


def policy_off(config: Path, repo: Path, state: dict) -> bool:
    if lib.read_policy(config):
        return False
    lib.log.info("auto-update disabled by config — running as checked out")
    lib.write_version(config, repo)
    lib.save_state(config, state)
    return True


def apply_hold(repo: Path, config: Path, state: dict) -> int:
    """Pinned by a rollback: never fetch, just make sure HEAD is the hold
    and any owed venv resync happens."""
    hold = state["hold"]
    current = lib.head_sha(repo)
    if current != hold:
        if not lib.reset_hard(repo, hold):
            lib.log.warning("could not reset to hold %s", hold)
            return 1
    if state["venv_dirty"]:
        state["venv_dirty"] = not lib.sync_venv(repo)
    lib.write_version(config, repo)
    lib.save_state(config, state)
    lib.log.info("holding at %s", hold)
    return 0


def rollback_to_lkg(repo: Path, config: Path, state: dict, head: str,
                    reason: str) -> int:
    """Shared with the pending backstop: HEAD is a commit that never
    proved healthy, and LKG is still available."""
    lib.log.info("%s — rolling back to last-known-good %s", reason,
                 state["lkg"])
    if not lib.reset_hard(repo, state["lkg"]):
        lib.log.warning("rollback reset failed")
        return 1
    if lib.diff_touches(repo, head, state["lkg"], "pyproject.toml"):
        if lib.sync_venv(repo):
            state["last_sync"] = state["lkg"]
        else:
            state["venv_dirty"] = True
    state.update(hold=state["lkg"], bad=head, pending=None, fails=0)
    lib.write_version(config, repo)
    lib.save_state(config, state)
    return 0


def update_to_target(repo: Path, config: Path, state: dict) -> int:
    current = lib.head_sha(repo)
    if current is None:
        lib.log.warning("no HEAD — leaving the checkout alone")
        return 0

    fetched = lib.git(repo, "fetch", "--prune", "origin",
                      timeout=lib.FETCH_TIMEOUT)
    if fetched is None:
        lib.log.info("fetch failed (offline?) — running the current code")
        lib.write_version(config, repo)
        lib.save_state(config, state)
        return 0

    target = lib.git(repo, "rev-parse", "--verify",
                     f"{lib.TARGET_REF}^{{commit}}")
    if target is None:
        lib.log.warning("%s is missing — running the current code",
                        lib.TARGET_REF)
        return 0

    if state["bad"] and target == state["bad"]:
        lib.log.info("main is still at the failed commit %s — staying on"
                     " %s", state["bad"], state["lkg"])
        if state["lkg"] and current != state["lkg"]:
            if not lib.reset_hard(repo, state["lkg"]):
                return 1
        state["hold"] = state["lkg"]
        lib.write_version(config, repo)
        lib.save_state(config, state)
        return 0

    if current == target and not state["venv_dirty"] and \
            state["last_sync"] in (None, target):
        # fast no-op: up to date, and the venv matches this commit
        lib.write_version(config, repo)
        state["last_sync"] = state["last_sync"] or target
        lib.save_state(config, state)
        return 0

    if current != target:
        if lib.tree_dirty(repo):
            lib.log.warning("discarding local changes in %s — it is a"
                            " deployment mirror", repo)
        ahead = lib.git(repo, "rev-list", "--count",
                        f"{lib.TARGET_REF}..HEAD")
        if ahead not in (None, "0"):
            lib.log.warning("discarding %s local commit(s) ahead of %s",
                            ahead, lib.TARGET_REF)
        # last-known-good BEFORE the move: a crash mid-reset still has
        # a rollback target
        state.update(lkg=current, hold=None)
        lib.save_state(config, state)
        if not lib.reset_hard(repo, target):
            lib.log.warning("reset --hard to %s failed", target)
            return 1

    resync = state["venv_dirty"] or (
        state["last_sync"] is not None and state["last_sync"] != target
        and lib.diff_touches(repo, state["last_sync"], target,
                             "pyproject.toml"))
    # last_sync None = the README just installed this exact checkout:
    # no pip run, and no ertftm070 recompile on first boot
    if resync:
        state["venv_dirty"] = not lib.sync_venv(repo)

    state.update(last_sync=target, pending=target, bad=None,
                 venv_dirty=state["venv_dirty"])
    lib.write_version(config, repo)
    lib.save_state(config, state)

    if lib.git(repo, "cat-file", "-e", f"{target}:deploy/healthcheck.py") \
            is None:
        lib.log.warning("the new version has no deploy/healthcheck.py —"
                        " rollback will wait for the next boot's pending"
                        " check")
    # the checkout reached the target either way; a failed resync is
    # still an exit 1 so the unit shows red in journald
    return 1 if resync and state["venv_dirty"] else 0


def main(argv=None) -> int:
    lib.setup_logging()
    args = parse_args(argv)
    repo: Path = args.repo
    config: Path = args.config
    if not (repo / ".git").is_dir():
        lib.log.info("%s is not a git checkout — nothing to update", repo)
        return 0
    state = lib.load_state(config)
    if policy_off(config, repo, state):
        return 0
    lkg = still_pending(repo, state)
    if lkg:
        state["pending"] = None
        return rollback_to_lkg(repo, config, state, lib.head_sha(repo),
                               "the deployed commit was never confirmed")
    if state["pending"]:
        state["pending"] = None  # HEAD moved on without us; nothing to confirm
        lib.save_state(config, state)
    if state["hold"]:
        return apply_hold(repo, config, state)
    return update_to_target(repo, config, state)


if __name__ == "__main__":
    raise SystemExit(main())
