"""The deployed-version stamp next to the config, with safe fallbacks."""

from wintermode import __version__
from wintermode.version import read_deployed_version, version_path


def test_no_stamp_falls_back_to_installed_version(tmp_path):
    assert read_deployed_version(tmp_path / "config.json") == __version__


def test_stamp_is_read_stripped(tmp_path):
    (tmp_path / "version").write_text("  v1.2.3-7-g31ff60b\n")
    assert read_deployed_version(tmp_path / "config.json") == "v1.2.3-7-g31ff60b"


def test_garbage_stamps_fall_back(tmp_path):
    version_path(tmp_path / "config.json").write_text("")
    assert read_deployed_version(tmp_path / "config.json") == __version__
    version_path(tmp_path / "config.json").write_text("x" * 65)
    assert read_deployed_version(tmp_path / "config.json") == __version__
    version_path(tmp_path / "config.json").write_text("two\nlines\n")
    assert read_deployed_version(tmp_path / "config.json") == __version__
    version_path(tmp_path / "config.json").write_bytes(b"\xff\xfe\x00")
    assert read_deployed_version(tmp_path / "config.json") == __version__
