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
    path.write_text(json.dumps({"dummy": {"count": 7}}))
    config = Config(path)
    config.save()
    assert json.loads(path.read_text())["dummy"] == {"count": 7}


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
    config.update_module("dummy", {"count": 5})
    reloaded = json.loads(path.read_text())
    assert reloaded["theme"] == "night"
    assert reloaded["dummy"] == {"count": 5}
