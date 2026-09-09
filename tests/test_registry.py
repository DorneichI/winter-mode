"""Module discovery and enabled/order bookkeeping."""

from wintermode.registry import Registry, discover

MODULE_SOURCE = '''
class MODULE:
    id = "{name}"
    title = "{name}".upper()
    interval = 0
    config_schema = None
    actions = []

    def render(self, draw, ctx):
        return True

    def on_tap(self, x, y, ctx):
        return False

    def status_items(self, ctx):
        return []

    def on_action(self, action_id, ctx):
        pass
'''


def write_module(base, name, source=MODULE_SOURCE):
    module_dir = base / name
    module_dir.mkdir()
    (module_dir / "module.py").write_text(source.format(name=name))
    return module_dir


def test_discovery_finds_valid_modules_sorted(tmp_path):
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    found = discover(tmp_path)
    assert [m.id for m in found] == ["alpha", "beta"]


def test_discovery_skips_invalid_ids_and_missing_files(tmp_path, caplog):
    (tmp_path / "bad name").mkdir()
    write_module(tmp_path, "1starts-with-digit")
    (tmp_path / "no_module_py").mkdir()  # dir without module.py
    found = discover(tmp_path)
    assert found == []


def test_discovery_skips_id_dirname_mismatch(tmp_path, caplog):
    write_module(tmp_path, "alpha").joinpath("module.py").write_text(
        MODULE_SOURCE.format(name="beta"))
    assert discover(tmp_path) == []


def test_discovery_survives_broken_imports(tmp_path, caplog):
    module_dir = write_module(tmp_path, "broken")
    (module_dir / "module.py").write_text("raise RuntimeError('boom')")
    write_module(tmp_path, "fine")
    assert [m.id for m in discover(tmp_path)] == ["fine"]


def test_registry_order_comes_from_config(config, fake_module):
    registry = Registry([fake_module("clock"), fake_module("dummy"),
                         fake_module("settings")], config)
    config.update({"modules": ["dummy", "clock"]})
    registry.refresh()
    # settings pinned first, then config order
    assert [m.id for m in registry.home_order()] == [
        "settings", "dummy", "clock"]


def test_registry_heals_the_modules_array(config, fake_module):
    config.update({"modules": ["ghost", "clock"]})
    registry = Registry([fake_module("clock"), fake_module("dummy")], config)
    registry.refresh()
    assert registry.enabled_ids() == ["clock", "dummy"]  # ghost dropped, dummy appended
    assert config.data["modules"] == ["clock", "dummy"]


def test_registry_validates_module_namespaces(config, fake_module):
    module = fake_module(
        "dummy",
        config_schema={"count": {"type": "int", "min": 0, "max": 99,
                                 "default": 0}},
    )
    config.update_module("dummy", {"count": 5000})  # out of bounds
    Registry([module], config).validate_namespaces()
    assert config.data["dummy"]["count"] == 99  # ints clamp, not fall back


def test_registry_get_and_contains(config, fake_module):
    registry = Registry([fake_module("clock")], config)
    assert "clock" in registry
    assert "nope" not in registry
    assert registry.get("clock").id == "clock"
    assert registry.get("nope") is None
