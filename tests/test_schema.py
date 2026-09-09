"""The config DSL: validation/coercion and form-state transitions."""

from wintermode import schema

SCHEMA = {
    "flag": {"type": "bool", "default": False},
    "mode": {"type": "choice", "options": ["count", "wave", "off"],
             "default": "count"},
    "count": {"type": "int", "min": 0, "max": 99, "default": 0},
    "greeting": {"type": "text", "maxlength": 8, "default": "hello"},
}


def test_missing_keys_filled_with_defaults():
    assert schema.validate(SCHEMA, {}) == {
        "flag": False, "mode": "count", "count": 0, "greeting": "hello",
    }


def test_bool_coerces_strings_and_ints():
    out = schema.validate({"f": {"type": "bool", "default": False}},
                          {"f": "false"})
    assert out == {"f": False}
    out = schema.validate({"f": {"type": "bool", "default": False}},
                          {"f": "1"})
    assert out == {"f": True}
    out = schema.validate({"f": {"type": "bool", "default": False}}, {"f": 1})
    assert out == {"f": True}


def test_bool_rejects_garbage_with_default():
    out = schema.validate({"f": {"type": "bool", "default": True}},
                          {"f": "not-a-bool"})
    assert out == {"f": True}


def test_choice_outside_options_falls_back(caplog):
    out = schema.validate(SCHEMA, {"mode": "bogus"})
    assert out["mode"] == "count"


def test_int_clamps_to_bounds():
    assert schema.validate(SCHEMA, {"count": -5})["count"] == 0
    assert schema.validate(SCHEMA, {"count": 500})["count"] == 99
    assert schema.validate(SCHEMA, {"count": "42"})["count"] == 42


def test_int_rejects_garbage_with_default(caplog):
    assert schema.validate(SCHEMA, {"count": "nope"})["count"] == 0


def test_text_truncates_to_maxlength():
    out = schema.validate(SCHEMA, {"greeting": "abcdefghijkl"})
    assert out["greeting"] == "abcdefgh"


def test_unknown_keys_are_dropped():
    out = schema.validate(SCHEMA, {"extra": 1, "mode": "wave"})
    assert "extra" not in out
    assert out["mode"] == "wave"


def test_toggle_flips_bool():
    spec = SCHEMA["flag"]
    assert schema.toggle_bool(spec, False) is True
    assert schema.toggle_bool(spec, True) is False


def test_cycle_wraps_around():
    spec = SCHEMA["mode"]
    assert schema.cycle_choice(spec, "count") == "wave"
    assert schema.cycle_choice(spec, "off") == "count"
    assert schema.cycle_choice(spec, "bogus") == "count"


def test_step_clamps_at_bounds():
    spec = SCHEMA["count"]
    assert schema.step_int(spec, 0, -1) == 0
    assert schema.step_int(spec, 99, 1) == 99
    assert schema.step_int(spec, 41, 1) == 42


def test_time_type_accepts_valid_and_rejects_garbage(caplog):
    from wintermode.schema import validate
    assert validate({"t": {"type": "time", "default": "07:00"}},
                    {"t": "23:59"}) == {"t": "23:59"}
    assert validate({"t": {"type": "time", "default": "07:00"}},
                    {"t": "25:00"}) == {"t": "07:00"}
    assert validate({"t": {"type": "time", "default": "07:00"}},
                    {"t": "7:30"}) == {"t": "07:00"}
    assert validate({"t": {"type": "time", "default": "07:00"}},
                    {"t": None}) == {"t": "07:00"}


def test_step_time_bumps_and_wraps():
    from wintermode.schema import step_time
    assert step_time("07:00", "hour", 1) == "08:00"
    assert step_time("23:00", "hour", 1) == "00:00"
    assert step_time("00:00", "hour", -1) == "23:00"
    assert step_time("07:00", "minute", 1) == "07:05"
    assert step_time("07:55", "minute", 1) == "07:00"
    assert step_time("07:00", "minute", -1) == "07:55"


def test_visible_if_conditions():
    from wintermode.schema import visible
    spec = {"type": "time", "visible_if": {"field": "theme", "equals": "auto"}}
    assert visible(spec, {"theme": "auto"}) is True
    assert visible(spec, {"theme": "dark"}) is False
    assert visible(spec, {}) is False  # field missing -> not shown
    assert visible({"type": "time"}, {"theme": "auto"}) is True  # no condition
