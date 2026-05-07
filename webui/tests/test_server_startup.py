from fastapi.testclient import TestClient

import webui.server as server


def test_webui_startup_does_not_autostart_gost_by_default(monkeypatch):
    calls = []
    monkeypatch.delenv("WEBUI_AUTOSTART_GOST", raising=False)
    monkeypatch.setattr(server, "ensure_gost_alive", lambda: calls.append("called"))

    with TestClient(server.create_app()) as client:
        assert client.get("/api/healthz").status_code == 200

    assert calls == []


def test_webui_startup_can_autostart_gost_when_explicitly_enabled(monkeypatch):
    calls = []
    monkeypatch.setenv("WEBUI_AUTOSTART_GOST", "1")
    monkeypatch.setattr(server, "ensure_gost_alive", lambda: calls.append("called"))

    with TestClient(server.create_app()) as client:
        assert client.get("/api/healthz").status_code == 200

    assert calls == ["called"]


def test_get_bind_settings_default_loopback(monkeypatch):
    monkeypatch.delenv("WEBUI_HOST", raising=False)
    monkeypatch.delenv("WEBUI_PORT", raising=False)

    assert server._get_bind_settings() == ("127.0.0.1", 8765)


def test_get_bind_settings_reads_env(monkeypatch):
    monkeypatch.setenv("WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("WEBUI_PORT", "8877")

    assert server._get_bind_settings() == ("0.0.0.0", 8877)
