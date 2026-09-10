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
    config.data["theme"] = "night"
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError()))
    config.save()
    # the original file still holds the defaults; the tmp file may linger
    assert json.loads(path.read_text())["theme"] == "dark"


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
