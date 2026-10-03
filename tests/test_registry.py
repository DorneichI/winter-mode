"""Module discovery and enabled/order bookkeeping."""

import json

from wintermode.registry import Registry, discover

MODULE_SOURCE = '''
class _Impl:
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


MODULE = _Impl()  # an instance: a class does not speak the protocol
'''


def write_module(base, name, source=MODULE_SOURCE):
    module_dir = base / name
    module_dir.mkdir()
    (module_dir / "module.py").write_text(source.format(name=name))
    return module_dir


# status_items is optional — the contract templates below cover "absent"
# and "present but broken"; the {name} placeholder must survive the edit
NO_STATUS_SOURCE = MODULE_SOURCE.replace(
    "    def status_items(self, ctx):\n        return []\n\n", "")
BROKEN_STATUS_SOURCE = MODULE_SOURCE.replace(
    "    def status_items(self, ctx):\n        return []",
    "    status_items = 3")


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


def test_discovery_rejects_a_bare_class(tmp_path, caplog):
    # `MODULE = MyClock` with the parens forgotten used to pass discovery
    # and then die on the first draw: every method was called unbound
    write_module(tmp_path, "unwrapped",
                 MODULE_SOURCE.replace("MODULE = _Impl()", "MODULE = _Impl"))
    assert discover(tmp_path) == []


def test_discovery_accepts_an_instance(tmp_path):
    write_module(tmp_path, "wrapped")
    assert [m.id for m in discover(tmp_path)] == ["wrapped"]


def test_discovery_accepts_a_module_without_status_items(tmp_path):
    # the method is optional: absent means "does not advertise"
    write_module(tmp_path, "quiet", source=NO_STATUS_SOURCE)
    assert [m.id for m in discover(tmp_path)] == ["quiet"]


def test_discovery_rejects_a_non_callable_status_items(tmp_path, caplog):
    # a typo'd method must fail loudly at boot, not silently hide the
    # module's bar content — the whole module is skipped, like any other
    # contract violation
    write_module(tmp_path, "broken_bar", source=BROKEN_STATUS_SOURCE)
    assert discover(tmp_path) == []
    assert "status_items" in caplog.text


def test_registry_order_comes_from_config(config, fake_module):
    registry = Registry([fake_module("clock"), fake_module("boston"),
                         fake_module("settings")], config)
    config.update({"modules": ["boston", "clock"]})
    registry.refresh()
    # settings pinned first, then config order
    assert [m.id for m in registry.home_order()] == [
        "settings", "boston", "clock"]


def test_registry_heals_the_modules_array(config, fake_module):
    config.update({"modules": ["ghost", "clock"]})
    registry = Registry([fake_module("clock"), fake_module("boston")], config)
    registry.refresh()
    # ghost dropped, boston appended
    assert registry.enabled_ids() == ["clock", "boston"]
    assert config.data["modules"] == ["clock", "boston"]


def test_statusbar_ids_lists_only_advertisers(config, fake_module):
    registry = Registry([fake_module("clock"),
                         fake_module("boston", publish_status=False)],
                        config)
    assert registry.statusbar_ids() == ["clock"]


def test_statusbar_ids_is_live(config, fake_module):
    # a module swapped into the registry mid-run changes the result on
    # the next call — nothing is cached at refresh time
    registry = Registry([fake_module("clock"), fake_module("boston")], config)
    assert registry.statusbar_ids() == ["clock", "boston"]
    registry._all["boston"] = fake_module("boston", publish_status=False)
    assert registry.statusbar_ids() == ["clock"]


def test_registry_heals_stale_statusbar_toggles(config, fake_module):
    config.update({"statusbar": {"clock": True, "ghost": False}})
    Registry([fake_module("clock")], config)
    # the toggle for a module that no longer advertises is dropped, in
    # the file as well as in memory
    assert config.data["statusbar"] == {"clock": True}
    assert json.loads(config.path.read_text())["statusbar"] == {"clock": True}


def test_statusbar_heal_does_not_loop_on_local_overlay_keys(tmp_path,
                                                            fake_module):
    # a stale key in the gitignored overlay must not make the heal
    # rewrite the tracked file on every boot: the heal compares the base
    # file's map, never the merged view
    from wintermode.config import Config

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"statusbar": {"clock": True}}))
    (tmp_path / "config.local.json").write_text(
        json.dumps({"statusbar": {"ghost": False}}))
    registry = Registry([fake_module("clock")], Config(path))
    before = path.read_text()
    registry.refresh()
    assert path.read_text() == before


def test_registry_validates_module_namespaces(config, fake_module):
    module = fake_module(
        "boston",
        config_schema={"count": {"type": "int", "min": 0, "max": 99,
                                 "default": 0}},
    )
    config.update_module("boston", {"count": 5000})  # out of bounds
    Registry([module], config).validate_namespaces()
    assert config.data["boston"]["count"] == 99  # ints clamp, not fall back


def test_registry_get_and_contains(config, fake_module):
    registry = Registry([fake_module("clock")], config)
    assert "clock" in registry
    assert "nope" not in registry
    assert registry.get("clock").id == "clock"
    assert registry.get("nope") is None


def test_discovery_finds_the_real_skeleton_modules():
    found = discover()
    assert [m.id for m in found] == ["boston", "clock", "settings"]


def test_a_scalar_namespace_is_healed_instead_of_stopping_the_boot(
        config, fake_module):
    """`"boston": 5` is an ordinary hand-edit; it must cost that module's
    settings, not the first frame of the day."""
    config.update({"boston": 5})
    module = fake_module("boston",
                         config_schema={"count": {"type": "int", "default": 1}})
    Registry([module], config).validate_namespaces()  # must not raise
    assert config.data["boston"]["count"] == 1


def test_healing_compares_against_the_file_it_writes(config, fake_module):
    """A bad overlay value must not make the tracked file be rewritten on
    every single boot."""
    path = config.path
    path.write_text(json.dumps({"clock": {"count": 1}}))
    (path.parent / "config.local.json").write_text(
        json.dumps({"clock": {"count": "not-an-int"}}))
    module = fake_module("clock",
                         config_schema={"count": {"type": "int", "default": 0}})
    registry = Registry([module], config)
    registry.validate_namespaces()
    first = path.read_text()
    registry.validate_namespaces()
    assert path.read_text() == first  # the repair does not repeat
