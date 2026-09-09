"""The web companion: REST endpoints against a real server on port 0."""

import http.client
import json
import queue

import pytest

from wintermode.registry import Registry
from wintermode.web.server import WebServer


@pytest.fixture
def web(config, fake_module):
    modules = [
        fake_module("clock", config_schema={
            "format24": {"type": "bool", "default": True}}),
        fake_module("dummy", actions=[{"id": "reset", "title": "Reset"}]),
    ]
    registry = Registry(modules, config)
    registry.validate_namespaces()
    actions = queue.Queue()
    server = WebServer(config, registry, actions, port=0)
    server.start()
    port = server._httpd.server_address[1]
    yield server, actions, config, registry, port
    server.stop()


def request(method, port, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = None
    headers = {}
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    conn.request(method, path, payload, headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    try:
        return response.status, json.loads(data)
    except ValueError:
        return response.status, data


def test_modules_endpoint_lists_modules_with_schemas(web):
    _server, _actions, _config, _registry, port = web
    status, payload = request("GET", port, "/api/modules")
    assert status == 200
    ids = [m["id"] for m in payload]
    assert ids == ["clock", "dummy"]
    assert payload[0]["schema"] == {"format24": {"type": "bool",
                                                 "default": True}}


def test_module_config_get_and_put_roundtrip(web, tmp_path):
    _server, _actions, config, _registry, port = web
    status, payload = request("GET", port, "/api/modules/clock/config")
    assert status == 200
    assert payload["values"] == {"format24": True}  # the schema default
    status, payload = request("PUT", port, "/api/modules/clock/config",
                              {"format24": True})
    assert status == 200
    assert payload["values"]["format24"] is True
    assert json.loads((tmp_path / "config.json").read_text())["clock"] == {
        "format24": True}


def test_module_config_put_rejects_garbage(web):
    _server, _actions, _config, _registry, port = web
    status, _payload = request("PUT", port, "/api/modules/clock/config",
                               {"format24": "bogus"})
    assert status == 400
    status, _payload = request("PUT", port, "/api/modules/clock/config",
                               {"no_such_key": 1})
    assert status == 400


def test_unknown_module_is_404(web):
    _server, _actions, _config, _registry, port = web
    assert request("GET", port, "/api/modules/ghost/config")[0] == 404


def test_action_post_enqueues_for_the_main_loop(web):
    _server, actions, _config, _registry, port = web
    status, payload = request("POST", port,
                              "/api/modules/dummy/actions/reset")
    assert status == 200 and payload == {"ok": True}
    assert actions.get_nowait() == ("dummy", "reset")
    status, _payload = request("POST", port,
                               "/api/modules/dummy/actions/nope")
    assert status == 400


def test_device_payload_and_group_put(web):
    _server, _actions, config, _registry, port = web
    status, device = request("GET", port, "/api/device")
    assert status == 200
    assert device["theme"]["name"] == "dark"
    assert set(device["tokens"]) == {"bg", "fg", "accent", "dim", "border"}
    assert [g["id"] for g in device["groups"]] == ["display", "statusbar"]
    before = config.generation
    status, _payload = request("PUT", port, "/api/device/display",
                               {"theme": "light"})
    assert status == 200
    assert config.data["theme"] == "light"
    assert config.generation == before + 1


def test_device_put_rejects_bad_values(web):
    _server, _actions, _config, _registry, port = web
    status, _payload = request("PUT", port, "/api/device/display",
                               {"theme": "vaporwave"})
    assert status == 400


def test_index_page_is_served(web):
    _server, _actions, _config, _registry, port = web
    status, page = request("GET", port, "/")
    assert status == 200
    assert b"fetch(" in page


def test_font_is_served(web):
    _server, _actions, _config, _registry, port = web
    status, data = request("GET", port, "/font/3270-Regular.ttf")
    assert status == 200
    assert len(data) > 100_000
    assert request("GET", port, "/font/evil.ttf")[0] == 404
