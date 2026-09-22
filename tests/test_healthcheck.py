"""The post-boot healthcheck: confirm or roll back.

The rollback paths run real git resets in the conftest tmp repos; only
the HTTP probe is faked (or, once, exercised for real against a
ThreadingHTTPServer on port 0).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from conftest import git_commit, git_describe, git_sha, run_git


def make_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"theme": "dark"}))
    return config


def read_state(config: Path) -> dict:
    return json.loads((config.parent / "update-state.json").read_text())


def write_state(config: Path, **values) -> None:
    (config.parent / "update-state.json").write_text(json.dumps(values))


def run_healthcheck(deploy, repo: Path, config: Path, probe=None) -> int:
    if probe is not None:
        with patch.object(deploy.lib, "probe_http", probe):
            return deploy.healthcheck.main(
                ["--repo", str(repo), "--config", str(config)])
    return deploy.healthcheck.main(
        ["--repo", str(repo), "--config", str(config)])


def healthy(_url=None):
    return {"version": "x", "theme": {"name": "dark"}}


# --- probe_http, for real ----------------------------------------------------


def test_probe_http_round_trips_a_real_server(deploy):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/ok":
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/ok"
        assert deploy.lib.probe_http(url) == {"ok": True}
        assert deploy.lib.probe_http(url[:-3] + "nope") is None
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert deploy.lib.probe_http(url) is None  # nothing answers now


# --- the healthy path ----------------------------------------------------------


def test_healthy_confirms_the_deployed_commit(deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    run_git(git_repo.work, "reset", "--hard", git_repo.second)
    write_state(config, lkg=git_repo.first, hold=git_repo.second,
                pending=git_repo.second, bad=git_repo.first)
    assert run_healthcheck(deploy, git_repo.work, config, healthy) == 0
    state = read_state(config)
    assert state["hold"] is None
    assert state["pending"] is None
    assert state["bad"] == git_repo.first  # not head: kept (loop rule)


def test_healthy_clears_bad_when_the_failed_commit_now_boots(
        deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    run_git(git_repo.work, "reset", "--hard", git_repo.second)
    write_state(config, lkg=git_repo.first, bad=git_repo.second)
    assert run_healthcheck(deploy, git_repo.work, config, healthy) == 0
    assert read_state(config)["bad"] is None


def test_healthy_keeps_bad_while_running_something_else(
        deploy, git_repo, tmp_path):
    # the loop-prevention rule: after a rollback to LKG, the failed
    # commit stays marked so the updater does not re-apply it
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, bad=git_repo.second)
    assert run_healthcheck(deploy, git_repo.work, config, healthy) == 0
    assert read_state(config)["bad"] == git_repo.second


# --- the rollback paths ---------------------------------------------------------


def test_unhealthy_new_commit_rolls_back_to_lkg(deploy, git_repo,
                                                tmp_path):
    config = make_config(tmp_path)
    run_git(git_repo.work, "reset", "--hard", git_repo.second)
    write_state(config, lkg=git_repo.first)
    assert run_healthcheck(deploy, git_repo.work, config,
                           lambda url: None) == 1
    assert git_sha(git_repo.work) == git_repo.first
    state = read_state(config)
    assert state["hold"] == git_repo.first
    assert state["bad"] == git_repo.second
    assert state["pending"] is None
    assert (tmp_path / "version").read_text().strip() == \
        git_describe(git_repo.work)


def test_unhealthy_lkg_itself_is_a_human_problem(deploy, git_repo,
                                                 tmp_path):
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, hold=git_repo.first,
                bad=git_repo.second, pending=git_repo.second)
    assert run_healthcheck(deploy, git_repo.work, config,
                           lambda url: None) == 1
    assert git_sha(git_repo.work) == git_repo.first  # unchanged
    state = read_state(config)
    assert state["hold"] is None and state["bad"] is None
    assert state["pending"] is None


def test_unhealthy_with_no_lkg_leaves_the_checkout_alone(
        deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    assert run_healthcheck(deploy, git_repo.work, config,
                           lambda url: None) == 1
    assert git_sha(git_repo.work) == git_repo.first


def test_rollback_resyncs_the_venv_when_pyproject_changed(
        deploy, git_repo, tmp_path, monkeypatch):
    config = make_config(tmp_path)
    third = git_commit(git_repo.seed, "pyproject.toml",
                       '[project]\nname = "w"\ndependencies = ["y"]\n')
    run_git(git_repo.seed, "push", "origin", "main")
    run_git(git_repo.work, "fetch", "origin")
    run_git(git_repo.work, "reset", "--hard", third)
    write_state(config, lkg=git_repo.first)
    calls = []
    monkeypatch.setattr(deploy.lib, "sync_venv",
                        lambda repo: calls.append(repo) or True)
    assert run_healthcheck(deploy, git_repo.work, config,
                           lambda url: None) == 1
    assert calls == [git_repo.work]
    assert read_state(config)["last_sync"] == git_repo.first


def test_rollback_with_failing_pip_marks_the_venv_dirty(
        deploy, git_repo, tmp_path, monkeypatch):
    config = make_config(tmp_path)
    third = git_commit(git_repo.seed, "pyproject.toml",
                       '[project]\nname = "w"\ndependencies = ["y"]\n')
    run_git(git_repo.seed, "push", "origin", "main")
    run_git(git_repo.work, "fetch", "origin")
    run_git(git_repo.work, "reset", "--hard", third)
    write_state(config, lkg=git_repo.first)
    monkeypatch.setattr(deploy.lib, "sync_venv", lambda repo: False)
    assert run_healthcheck(deploy, git_repo.work, config,
                           lambda url: None) == 1
    assert read_state(config)["venv_dirty"] is True


def test_wait_healthy_times_out_promptly(deploy):
    started = [0]

    def probe(_url=None):
        started[0] += 1
        return None

    assert deploy.healthcheck.wait_healthy(
        "http://x", 0.1, 0.01, probe=probe) is None
    assert started[0] >= 2  # it really did poll, and stopped on deadline
