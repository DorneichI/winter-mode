"""Config: defaults, atomic saves, generation, self-healing."""

import json

from wintermode.config import Config


def test_missing_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    config = Config(path)
    assert path.exists()
    assert config.data["theme"] == "dark"
    assert config.data["modules"] == []
    assert config.data["statusbar_rotate"] == 10
    assert config.data["display"] == {
        "mode": "always_on", "idle_seconds": 60,
        "light_from": "07:00", "light_to": "19:00",
    }


def test_extra_top_level_namespaces_survive_a_save_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"boston": {"count": 7}}))
    config = Config(path)
    config.save()
    assert json.loads(path.read_text())["boston"] == {"count": 7}


def test_invalid_reserved_value_falls_back_with_log(tmp_path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": 42, "display": "not-a-dict"}))
    config = Config(path)
    assert config.data["theme"] == "dark"
    assert config.data["display"]["mode"] == "always_on"


def test_invalid_module_and_statusbar_containers_fall_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"modules": "clock", "statusbar": [1, 2]}))
    config = Config(path)
    assert config.data["modules"] == []
    assert config.data["statusbar"] == {}


def test_save_is_atomic(tmp_path, monkeypatch):
    import os

    path = tmp_path / "config.json"
    config = Config(path)
    monkeypatch.setattr(os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError()))
    config.update({"theme": "night"})  # its save() fails mid-write
    # the original file still holds the defaults; the tmp file may linger
    assert json.loads(path.read_text())["theme"] == "dark"
    assert config.data["theme"] == "night"  # the change lives in memory


def test_every_save_bumps_generation(tmp_path):
    config = Config(tmp_path / "config.json")
    before = config.generation
    config.save()
    assert config.generation == before + 1


def test_update_and_update_module_persist(tmp_path):
    path = tmp_path / "config.json"
    config = Config(path)
    config.update({"theme": "night"})
    config.update_module("boston", {"count": 5})
    reloaded = json.loads(path.read_text())
    assert reloaded["theme"] == "night"
    assert reloaded["boston"] == {"count": 5}


def test_update_module_with_a_schema_validates_the_write(tmp_path):
    # an unvalidated write persisted count=120 past max=99; the next boot
    # clamped it to 99, and "+" then made the number go DOWN.  The spec
    # is local: this tests Config, not any particular module.
    spec = {"count": {"type": "int", "min": 0, "max": 99, "default": 0}}

    config = Config(tmp_path / "config.json")
    config.update_module("boston", {"count": 120}, spec=spec)
    assert config.data["boston"]["count"] == 99
    assert config.update_module("boston", {"count": 3}, spec=spec)["count"] == 3
    # without a spec the caller keeps the old permissive behavior
    config.update_module("boston", {"count": 500})
    assert config.data["boston"]["count"] == 500


def test_local_overlay_merges_over_the_base(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"boston": {"mode": "transit"}}))
    (tmp_path / "config.local.json").write_text(
        json.dumps({"boston": {"api_key": "secret"}}))
    config = Config(path)
    # merged view holds both; the base file itself is untouched
    assert config.data["boston"] == {"mode": "transit", "api_key": "secret"}
    assert json.loads(path.read_text())["boston"] == {"mode": "transit"}


def test_update_local_writes_only_the_overlay(tmp_path):
    path = tmp_path / "config.json"
    config = Config(path)
    config.update_local({"boston": {"api_key": "secret"}})
    assert json.loads(path.read_text()).get("boston") is None
    assert json.loads((tmp_path / "config.local.json").read_text())["boston"] \
        == {"api_key": "secret"}
    assert config.data["boston"]["api_key"] == "secret"


def test_base_save_never_leaks_local_values(tmp_path):
    path = tmp_path / "config.json"
    config = Config(path)
    config.update_local({"boston": {"api_key": "secret"}})
    config.update({"theme": "night"})  # a normal write triggers save()
    on_disk = json.loads(path.read_text())
    assert on_disk["theme"] == "night"
    assert "api_key" not in json.dumps(on_disk)  # the secret stayed out


def test_unreadable_local_overlay_is_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"boston": {"mode": "transit"}}))
    (tmp_path / "config.local.json").write_text("{ not json")
    config = Config(path)
    assert config.data["boston"]["mode"] == "transit"


def test_a_corrupt_file_is_rewritten_not_just_healed_in_memory(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json")
    config = Config(path)
    assert config.data["theme"] == "dark"
    assert json.loads(path.read_text()) == config.data  # the repair stuck


def test_a_repairable_value_is_written_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": 42, "statusbar": {"clock": "false"}}))
    Config(path)
    on_disk = json.loads(path.read_text())
    assert on_disk["theme"] == "dark"
    assert on_disk["statusbar"]["clock"] is False  # not bool("false") == True


def test_a_healthy_file_is_not_rewritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": "light"}))
    before = path.stat().st_mtime_ns
    config = Config(path)
    assert config.data["theme"] == "light"
    assert path.stat().st_mtime_ns == before  # absent keys are not a repair


def test_overlay_reserved_keys_are_shaped_before_the_loop_reads_them(
        tmp_path):
    """The overlay is hand-editable, so it gets the same shape guarantee
    the tracked file gets — the main loop reads these every frame."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}))
    (tmp_path / "config.local.json").write_text(
        json.dumps({"display": "off", "statusbar": [1, 2]}))
    config = Config(path)
    assert config.data["display"]["mode"] == "always_on"
    assert config.data["statusbar"].get("clock", True) is True


def test_update_module_writes_only_the_keys_it_was_given(tmp_path):
    """A save carries the fields the user touched — nothing else reaches
    either file, and a local field reaches only the overlay."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}))
    config = Config(path)
    spec = {"mode": {"type": "text", "default": ""},
            "api_key": {"type": "text", "default": "", "local": True}}
    config.update_module("boston", {"mode": "walk"}, spec)
    assert json.loads(path.read_text())["boston"] == {"mode": "walk"}
    assert not (tmp_path / "config.local.json").exists()
    config.update_module("boston", {"api_key": "K"}, spec)
    tracked = json.loads(path.read_text())["boston"]
    overlay = json.loads((tmp_path / "config.local.json").read_text())
    assert "api_key" not in tracked  # the secret stays out of the commit
    assert overlay["boston"] == {"api_key": "K"}


def test_update_module_survives_a_key_the_schema_drops(tmp_path):
    """The schema drops unknown keys by design; a write must not raise
    halfway through leaving the file and memory disagreeing."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}))
    config = Config(path)
    spec = {"count": {"type": "int", "default": 0, "min": 0, "max": 99}}
    config.update_module("clock", {"count": 3, "typo": 1}, spec)
    assert json.loads(path.read_text())["clock"] == {"count": 3}
    assert config.data["clock"]["count"] == 3
