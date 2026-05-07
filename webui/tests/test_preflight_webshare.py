import respx
from httpx import Response

from webui.backend.preflight import webshare


def _login(client):
    client.post("/api/setup", json={"username": "admin", "password": "hunter2hunter2"})
    client.post("/api/login", json={"username": "admin", "password": "hunter2hunter2"})


@respx.mock
def test_webshare_ok(client):
    _login(client)
    respx.get("https://proxy.webshare.io/api/v2/proxy/list/").mock(
        return_value=Response(200, json={"count": 100, "results": [{"proxy_address": "1.2.3.4", "ports": {"socks5": 1080}}]})
    )
    r = client.post("/api/preflight/webshare", json={"api_key": "k"})
    body = r.json()
    assert body["status"] == "ok"


@respx.mock
def test_webshare_unauth(client):
    _login(client)
    respx.get("https://proxy.webshare.io/api/v2/proxy/list/").mock(
        return_value=Response(401, json={"detail": "Invalid token."})
    )
    r = client.post("/api/preflight/webshare", json={"api_key": "bad"})
    assert r.json()["status"] == "fail"


def test_webshare_preflight_uses_explicit_api_proxy(monkeypatch):
    seen = []
    monkeypatch.setattr(webshare, "resolve_system_proxy", lambda: None)

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"count": 100, "results": []}

    class FakeClient:
        def __init__(self, timeout=15.0, proxy=None):
            seen.append(proxy)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(webshare.httpx, "Client", FakeClient)

    result = webshare.check({
        "api_key": "secret",
        "api_proxy": "http://127.0.0.1:7897",
    })

    assert result.status == "ok"
    assert seen == ["http://127.0.0.1:7897"]
