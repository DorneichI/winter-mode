"""The boot updater, exercised against real tmp git repos.

Every test runs the actual update.py main() with `--repo` pointed at a
hermetic work clone and `--config` at a tmp config.json — the same
surface systemd uses, no mocking of git itself.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from conftest import git_commit, git_describe, git_sha, run_git


def make_config(tmp_path: Path, auto=None) -> Path:
    """A config.json the updater reads raw; None = no "updates" key."""
    payload: dict = {"theme": "dark"}
    if auto is not None:
        payload["updates"] = {"auto": auto}
    config = tmp_path / "config.json"
    config.write_text(json.dumps(payload))
    return config


def read_state(config: Path) -> dict:
    return json.loads((config.parent / "update-state.json").read_text())


def write_state(config: Path, **values) -> None:
    (config.parent / "update-state.json").write_text(json.dumps(values))


def run_update(deploy, repo: Path, config: Path) -> int:
    return deploy.update.main(["--repo", str(repo), "--config", str(config)])


# --- policy ----------------------------------------------------------------


def test_policy_defaults_to_auto_on(deploy):
    assert deploy.lib.read_policy(Path("/nonexistent/config.json")) is True


def test_policy_reads_unknown_but_unparseable_as_on(deploy, tmp_path):
    config = make_config(tmp_path)
    config.write_text("{ truncated")
    assert deploy.lib.read_policy(config) is True
    make_config(tmp_path, auto=5)  # not a namespace -> auto on
    assert deploy.lib.read_policy(config) is True


def test_policy_off_skips_everything(deploy, git_repo, tmp_path):
    config = make_config(tmp_path, auto=False)
    assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.first  # HEAD untouched
    # the version stamp is still refreshed, so the panel shows the truth
    assert (tmp_path / "version").read_text().strip() == \
        git_describe(git_repo.work)


# --- the happy path ---------------------------------------------------------


def test_first_run_moves_head_and_records_state(deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.second
    state = read_state(config)
    assert state["lkg"] == git_repo.first      # recorded BEFORE the move
    assert state["last_sync"] == git_repo.second
    assert state["pending"] == git_repo.second
    assert state["bad"] is None
    assert state["hold"] is None
    assert (tmp_path / "version").read_text().strip() == \
        git_describe(git_repo.work)


def test_second_run_with_no_new_commit_is_a_fast_noop(
        deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    run_update(deploy, git_repo.work, config)
    # the healthcheck confirmed the deployed commit, as it does every
    # healthy boot: pending is cleared the way on_healthy clears it
    write_state(config, lkg=git_repo.first, last_sync=git_repo.second,
                pending=None)
    reflog = len((git_repo.work / ".git" / "logs" / "HEAD").read_text()
                 .splitlines())
    state_before = deploy.lib.load_state(config)
    assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.second
    after = deploy.lib.load_state(config)
    for key in ("lkg", "hold", "last_sync", "pending", "bad"):
        assert after[key] == state_before[key]
    assert len((git_repo.work / ".git" / "logs" / "HEAD").read_text()
               .splitlines()) == reflog  # no reset, no move


def test_fetch_failure_runs_the_current_code(deploy, git_repo, tmp_path,
                                             caplog):
    config = make_config(tmp_path)
    run_git(git_repo.work, "remote", "set-url", "origin",
            str(tmp_path / "gone.git"))
    with caplog.at_level(logging.INFO, logger="updater"):
        assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.first  # fail open
    assert any("fetch failed" in record.message
               for record in caplog.records)


# --- dependency resync -------------------------------------------------------


def test_pyproject_change_triggers_one_venv_sync(deploy, git_repo,
                                                 tmp_path, monkeypatch):
    third = git_commit(git_repo.seed, "pyproject.toml",
                        '[project]\nname = "w"\ndependencies = ["newdep"]\n')
    run_git(git_repo.seed, "push", "origin", "main")
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, last_sync=git_repo.first)
    calls = []
    monkeypatch.setattr(deploy.lib, "sync_venv",
                        lambda repo: calls.append(repo) or True)
    assert run_update(deploy, git_repo.work, config) == 0
    assert calls == [git_repo.work]  # exactly once
    assert read_state(config)["last_sync"] == third


def test_pyproject_unchanged_skips_the_venv(deploy, git_repo, tmp_path,
                                            monkeypatch):
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, last_sync=git_repo.first)
    calls = []
    monkeypatch.setattr(deploy.lib, "sync_venv",
                        lambda repo: calls.append(repo) or True)
    assert run_update(deploy, git_repo.work, config) == 0
    assert calls == []  # code changed, deps did not


def test_pip_failure_exits_1_and_marks_the_venv_dirty(
        deploy, git_repo, tmp_path, monkeypatch):
    git_commit(git_repo.seed, "pyproject.toml",
                '[project]\nname = "w"\ndependencies = ["x"]\n')
    run_git(git_repo.seed, "push", "origin", "main")
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, last_sync=git_repo.first)
    monkeypatch.setattr(deploy.lib, "sync_venv", lambda repo: False)
    assert run_update(deploy, git_repo.work, config) == 1
    assert read_state(config)["venv_dirty"] is True


# --- rollback protections -----------------------------------------------------


def test_bad_target_stays_on_lkg(deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, bad=git_repo.second)
    assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.first  # no move onto the bad sha
    assert read_state(config)["hold"] == git_repo.first


def test_hold_forces_head_back_without_fetching(deploy, git_repo, tmp_path):
    config = make_config(tmp_path)
    write_state(config, lkg=git_repo.first, hold=git_repo.first)
    run_git(git_repo.work, "reset", "--hard", git_repo.second)
    # the remote is broken: any fetch attempt would fail — hold must not
    # even try
    run_git(git_repo.work, "remote", "set-url", "origin",
            str(tmp_path / "gone.git"))
    assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.first


def test_pending_unconfirmed_rolls_back_on_next_boot(deploy, git_repo,
                                                     tmp_path):
    config = make_config(tmp_path)
    run_git(git_repo.work, "reset", "--hard", git_repo.second)
    write_state(config, lkg=git_repo.first, pending=git_repo.second)
    assert run_update(deploy, git_repo.work, config) == 0
    assert git_sha(git_repo.work) == git_repo.first
    state = read_state(config)
    assert state["bad"] == git_repo.second
    assert state["hold"] == git_repo.first


def test_state_file_is_valid_json_after_every_path(deploy, git_repo,
                                                  tmp_path):
    config = make_config(tmp_path, auto=False)
    run_update(deploy, git_repo.work, config)
    json.loads((tmp_path / "update-state.json").read_text())  # no raise
    make_config(tmp_path)
    run_update(deploy, git_repo.work, config)
    read_state(config)  # no raise
    run_update(deploy, git_repo.work, config)
    read_state(config)  # no raise


def test_updater_sources_never_import_wintermode_or_shell_out(deploy):
    """The two invariants the whole design rests on.

    Line-anchored, not a substring search: the docstrings themselves say
    "never import wintermode".
    """
    import_line = re.compile(r"^\s*(import wintermode|from wintermode)")
    for name in ("updatelib", "update", "healthcheck"):
        source = Path(deploy.lib.__file__).parent / f"{name}.py"
        text = source.read_text()
        assert not import_line.search(text), name
        assert "shell=True" not in text, name
