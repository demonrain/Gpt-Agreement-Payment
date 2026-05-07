import urllib.error
import json
import uuid
from pathlib import Path

import requests

import pipeline


def _temp_config_path():
    base = Path(__file__).resolve().parents[2] / "output" / "test-temp"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"config.paypal.{uuid.uuid4().hex}.json"


def test_pipeline_resolve_outbound_proxy_uses_detected_windows_host_before_gateway(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", "1")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(pipeline, "_detect_windows_host_ip", lambda: "192.168.0.88", raising=False)
    monkeypatch.setattr(pipeline, "_detect_wsl_gateway_ip", lambda: "192.168.0.1", raising=False)

    attempts = []

    class FakeConn:
        def close(self):
            pass

    def fake_create_connection(endpoint, timeout=1):
        attempts.append(endpoint)
        if endpoint == ("192.168.0.88", 7897):
            return FakeConn()
        raise OSError("closed")

    monkeypatch.setattr(pipeline._sock, "create_connection", fake_create_connection)

    assert pipeline._resolve_outbound_proxy() == "http://192.168.0.88:7897"
    assert attempts[0] == ("192.168.0.88", 7897)


def test_pipeline_resolve_outbound_proxy_does_not_probe_host_proxy_by_default(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(
        pipeline,
        "_detect_windows_host_ip",
        lambda: (_ for _ in ()).throw(AssertionError("should not probe host IP")),
        raising=False,
    )

    assert pipeline._resolve_outbound_proxy() == ""


def test_pipeline_resolve_outbound_proxy_ignores_env_proxy_by_default(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://192.168.0.1:7897")
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)

    assert pipeline._resolve_outbound_proxy() == ""


def test_pipeline_resolve_outbound_proxy_allows_explicit_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://192.168.0.1:7897")
    monkeypatch.setenv("GPT_PAY_USE_ENV_PROXY", "1")

    assert pipeline._resolve_outbound_proxy() == "http://192.168.0.1:7897"


def test_pipeline_ensure_gost_uses_cached_proxy_when_webshare_times_out(monkeypatch):
    calls = []

    class TimeoutClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            calls.append(("client", api_key, timeout_s))

        def get_current_proxy(self):
            raise urllib.error.URLError("timed out")

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(pipeline, "WebshareClient", TimeoutClient)
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
            "last_proxy": {
                "proxy_address": "p.webshare.io",
                "port": 80,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            },
        },
    }) is True

    assert not [c for c in calls if c[0] == "client"]
    assert calls[-1][0] == "swap"
    assert calls[-1][1][:4] == ("p.webshare.io", 80, "user", "pass")


def test_pipeline_ensure_gost_prefers_manual_proxy_without_webshare_lookup(monkeypatch):
    calls = []

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(
        pipeline,
        "WebshareClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not query Webshare")),
    )
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
            "manual_proxy": {
                "proxy_address": "p.webshare.io",
                "port": 80,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            },
        },
    }) is True

    assert calls[-1][0] == "swap"
    assert calls[-1][1][:4] == ("p.webshare.io", 80, "user", "pass")


def test_swap_gost_relay_prefers_configured_chain_proxy(monkeypatch):
    popen_calls = []

    class FakeProc:
        def __init__(self):
            self.pid = 1234

        def poll(self):
            return None

    monkeypatch.setattr(pipeline.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(pipeline, "_resolve_outbound_proxy", lambda: "")
    monkeypatch.setattr(pipeline.time, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.os, "open", lambda *args, **kwargs: 9)
    monkeypatch.setattr(pipeline.os, "close", lambda *args, **kwargs: None)

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(pipeline.subprocess, "Popen", fake_popen)

    pipeline._swap_gost_relay(
        "p.webshare.io",
        10000,
        "user",
        "pass",
        listen_port=18898,
        upstream_scheme="http",
        chain_proxy="http://192.168.0.2:7897",
    )

    assert popen_calls
    assert "-F=http://192.168.0.2:7897" in popen_calls[0]
    assert popen_calls[0].index("-F=http://192.168.0.2:7897") < popen_calls[0].index(
        "-F=http://user:pass@p.webshare.io:10000"
    )


def test_pipeline_ensure_gost_persists_last_proxy_after_success(monkeypatch):
    cfg_path = _temp_config_path()
    cfg_path.write_text(json.dumps({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    }), encoding="utf-8")
    calls = []

    class SuccessClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            calls.append(("client", api_key, timeout_s))

        def get_current_proxy(self):
            return {
                "proxy_address": "proxy.example",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            }

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(pipeline, "WebshareClient", SuccessClient)
    monkeypatch.setattr(pipeline, "_swap_gost_relay", lambda *args, **kwargs: None)

    card_cfg = pipeline._read_card_cfg(str(cfg_path))
    assert pipeline._ensure_gost_alive(card_cfg, cfg_path=str(cfg_path)) is True

    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved["webshare"]["last_proxy"] == {
        "proxy_address": "proxy.example",
        "port": 8080,
        "username": "user",
        "password": "pass",
        "country_code": "US",
    }


def test_pipeline_ensure_gost_retries_webshare_api_via_detected_proxy_after_direct_timeout(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, api_key, timeout_s=30, api_proxy="", **kwargs):
            calls.append(("client", api_key, timeout_s, api_proxy))
            self.api_proxy = api_proxy

        def get_current_proxy(self):
            if not self.api_proxy:
                raise urllib.error.URLError("timed out")
            return {
                "proxy_address": "proxy.example",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            }

    class FakeConn:
        def close(self):
            pass

    def fake_create_connection(endpoint, timeout=1):
        if endpoint == ("192.168.0.88", 7897):
            return FakeConn()
        raise OSError("closed")

    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(pipeline, "_detect_windows_host_ip", lambda: "192.168.0.88", raising=False)
    monkeypatch.setattr(pipeline, "_detect_wsl_gateway_ip", lambda: "192.168.0.1", raising=False)
    monkeypatch.setattr(pipeline._sock, "create_connection", fake_create_connection)
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(pipeline, "WebshareClient", FakeClient)
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    }) is True

    assert ("client", "secret", 8, "") in calls
    assert ("client", "secret", 8, "http://192.168.0.88:7897") in calls
    assert calls[-1][0] == "swap"
    assert calls[-1][1][:4] == ("proxy.example", 8080, "user", "pass")


def test_pipeline_ensure_gost_does_not_probe_retry_proxy_when_direct_webshare_lookup_works(monkeypatch):
    calls = []

    class SuccessClient:
        def __init__(self, api_key, timeout_s=30, api_proxy="", **kwargs):
            calls.append(("client", api_key, timeout_s, api_proxy))

        def get_current_proxy(self):
            return {
                "proxy_address": "proxy.example",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            }

    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(
        pipeline,
        "_detect_host_outbound_proxy",
        lambda: (_ for _ in ()).throw(AssertionError("should not probe retry proxy")),
        raising=False,
    )
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(pipeline, "WebshareClient", SuccessClient)
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    }) is True

    assert calls[0] == ("client", "secret", 8, "")
    assert calls[-1][0] == "swap"


def test_webshare_client_uses_explicit_api_proxy(monkeypatch):
    handlers = []

    class FakeProxyHandler:
        def __init__(self, mapping):
            handlers.append(mapping)

    class FakeOpener:
        pass

    monkeypatch.setattr(pipeline.urllib.request, "ProxyHandler", FakeProxyHandler)
    monkeypatch.setattr(pipeline.urllib.request, "build_opener", lambda handler: FakeOpener())

    pipeline.WebshareClient("secret", api_proxy="http://127.0.0.1:7897")

    assert handlers == [{"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}]


def test_pipeline_ensure_gost_timeout_without_cache_returns_false(monkeypatch):
    class TimeoutClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            pass

        def get_current_proxy(self):
            raise TimeoutError("timed out")

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(pipeline, "WebshareClient", TimeoutClient)
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not start gost")),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    }) is False


def test_pipeline_ensure_gost_keeps_existing_listener_without_webshare_lookup(monkeypatch):
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "LISTEN 0 4096 *:18898 *:*"})(),
    )
    monkeypatch.setattr(pipeline, "_local_gost_egress_ok", lambda port: True)
    monkeypatch.setattr(
        pipeline,
        "WebshareClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not query Webshare")),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    }) is True


def test_pipeline_ensure_gost_restarts_existing_listener_when_egress_probe_fails(monkeypatch):
    calls = []

    class SuccessClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            calls.append(("client", api_key, timeout_s))

        def get_current_proxy(self):
            return {
                "proxy_address": "p.webshare.io",
                "port": 80,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            }

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "LISTEN 0 4096 *:18898 *:*"})(),
    )
    monkeypatch.setattr(pipeline, "_local_gost_egress_ok", lambda port: False)
    monkeypatch.setattr(pipeline, "WebshareClient", SuccessClient)
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    }) is True

    assert calls[-1][0] == "swap"


def test_pipeline_ensure_gost_restarts_lock_country_listener_when_egress_probe_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "LISTEN 0 4096 *:18898 *:*"})(),
    )
    monkeypatch.setattr(pipeline, "_local_gost_egress_ok", lambda port: False)
    monkeypatch.setattr(
        pipeline,
        "WebshareClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should use cached proxy")),
    )
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
            "lock_country": "GB",
            "last_proxy": {
                "proxy_address": "p.webshare.io",
                "port": 80,
                "username": "user",
                "password": "pass",
                "country_code": "GB",
            },
            "gost_chain_proxy": "http://192.168.0.2:7897",
        },
    }) is True

    assert calls[-1][0] == "swap"
    assert calls[-1][2]["chain_proxy"] == "http://192.168.0.2:7897"


def test_pipeline_ensure_gost_autodetects_chain_proxy_when_listener_is_broken(monkeypatch):
    calls = []

    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "LISTEN 0 4096 *:18898 *:*"})(),
    )
    monkeypatch.setattr(pipeline, "_local_gost_egress_ok", lambda port: False)
    monkeypatch.setattr(pipeline, "_detect_host_outbound_proxy", lambda: "http://192.168.0.2:7897")
    monkeypatch.setattr(
        pipeline,
        "WebshareClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should use cached proxy")),
    )
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    assert pipeline._ensure_gost_alive({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
            "last_proxy": {
                "proxy_address": "p.webshare.io",
                "port": 80,
                "username": "user",
                "password": "pass",
                "country_code": "GB",
            },
        },
    }) is True

    assert calls[-1][0] == "swap"
    assert calls[-1][2]["chain_proxy"] == "http://192.168.0.2:7897"


def test_local_gost_egress_probe_falls_back_to_next_ip_endpoint(monkeypatch):
    calls = []

    class FakeResponse:
        text = "203.0.113.10\n"

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.ConnectTimeout("first endpoint timed out")
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)

    assert pipeline._local_gost_egress_ok(18898) is True
    assert calls[:2] == ["http://api.ipify.org", "http://checkip.amazonaws.com"]


def test_rotate_webshare_ip_retries_api_via_detected_proxy_after_direct_timeout(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, api_key, timeout_s=30, api_proxy="", **kwargs):
            calls.append(("client", api_key, timeout_s, api_proxy))
            self.api_proxy = api_proxy

        def get_replacement_quota(self):
            if not self.api_proxy:
                raise urllib.error.URLError("timed out")
            return {"total": 1, "used": 0, "available": 1}

        def refresh_pool(self, country=""):
            if not self.api_proxy:
                raise urllib.error.URLError("timed out")
            calls.append(("refresh", country, self.api_proxy))

        def wait_for_fresh_proxy(self, prev_ip="", max_wait_s=120):
            return {
                "proxy_address": "proxy.example",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "country_code": "US",
                "valid": True,
            }

    class FakeConn:
        def close(self):
            pass

    def fake_create_connection(endpoint, timeout=1):
        if endpoint == ("192.168.0.88", 7897):
            return FakeConn()
        raise OSError("closed")

    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(pipeline, "_detect_windows_host_ip", lambda: "192.168.0.88", raising=False)
    monkeypatch.setattr(pipeline, "_detect_wsl_gateway_ip", lambda: "192.168.0.1", raising=False)
    monkeypatch.setattr(pipeline._sock, "create_connection", fake_create_connection)
    monkeypatch.setattr(pipeline, "WebshareClient", FakeClient)
    monkeypatch.setattr(
        pipeline,
        "_swap_gost_relay",
        lambda *args, **kwargs: calls.append(("swap", args, kwargs)),
    )

    px = pipeline._rotate_webshare_ip({
        "webshare": {
            "enabled": True,
            "api_key": "secret",
            "gost_listen_port": 18898,
        },
    })

    assert px["proxy_address"] == "proxy.example"
    assert ("client", "secret", 8, "") in calls
    assert ("client", "secret", 8, "http://192.168.0.88:7897") in calls
    assert calls[-1][0] == "swap"
