import json
import urllib.error
import uuid
from pathlib import Path

from webui.backend import gost_manager


def _temp_config_path():
    base = Path(__file__).resolve().parents[2] / "output" / "test-temp"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"config.paypal.{uuid.uuid4().hex}.json"


def _write_pay_config(path, webshare):
    path.write_text(json.dumps({"webshare": webshare}), encoding="utf-8")


def test_ensure_gost_uses_cached_proxy_when_webshare_times_out(monkeypatch):
    cfg = _temp_config_path()
    _write_pay_config(cfg, {
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
    })
    calls = []

    class TimeoutClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            calls.append(("client", api_key, timeout_s))

        def get_current_proxy(self):
            raise urllib.error.URLError("timed out")

    monkeypatch.setattr(gost_manager.s, "PAY_CONFIG_PATH", cfg)
    monkeypatch.setattr(gost_manager, "_port_listening", lambda port: False)
    monkeypatch.setattr(gost_manager, "_WebshareClient", TimeoutClient)
    monkeypatch.setattr(gost_manager, "_swap_gost_relay", lambda *args, **kwargs: calls.append(("swap", args, kwargs)))

    assert gost_manager.ensure_gost_alive() is True
    assert not [c for c in calls if c[0] == "client"]
    assert calls[-1][0] == "swap"
    assert calls[-1][1][:4] == ("p.webshare.io", 80, "user", "pass")


def test_ensure_gost_prefers_manual_proxy_without_webshare_lookup(monkeypatch):
    cfg = _temp_config_path()
    _write_pay_config(cfg, {
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
    })
    calls = []

    monkeypatch.setattr(gost_manager.s, "PAY_CONFIG_PATH", cfg)
    monkeypatch.setattr(gost_manager, "_port_listening", lambda port: False)
    monkeypatch.setattr(
        gost_manager,
        "_WebshareClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not query Webshare")),
    )
    monkeypatch.setattr(gost_manager, "_swap_gost_relay", lambda *args, **kwargs: calls.append(("swap", args, kwargs)))

    assert gost_manager.ensure_gost_alive() is True
    assert calls[-1][0] == "swap"
    assert calls[-1][1][:4] == ("p.webshare.io", 80, "user", "pass")


def test_webshare_client_uses_explicit_api_proxy(monkeypatch):
    handlers = []

    class FakeProxyHandler:
        def __init__(self, mapping):
            handlers.append(mapping)

    class FakeOpener:
        pass

    monkeypatch.setattr(gost_manager.urllib.request, "ProxyHandler", FakeProxyHandler)
    monkeypatch.setattr(gost_manager.urllib.request, "build_opener", lambda handler: FakeOpener())

    gost_manager._WebshareClient("secret", api_proxy="http://127.0.0.1:7897")

    assert handlers == [{"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}]


def test_ensure_gost_webshare_timeout_without_cache_returns_false(monkeypatch):
    cfg = _temp_config_path()
    _write_pay_config(cfg, {
        "enabled": True,
        "api_key": "secret",
        "gost_listen_port": 18898,
    })

    class TimeoutClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            self.timeout_s = timeout_s

        def get_current_proxy(self):
            raise TimeoutError("timed out")

    monkeypatch.setattr(gost_manager.s, "PAY_CONFIG_PATH", cfg)
    monkeypatch.setattr(gost_manager, "_port_listening", lambda port: False)
    monkeypatch.setattr(gost_manager, "_WebshareClient", TimeoutClient)
    monkeypatch.setattr(gost_manager, "_swap_gost_relay", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not start gost")))

    assert gost_manager.ensure_gost_alive() is False


def test_ensure_gost_caches_proxy_after_success(monkeypatch):
    cfg = _temp_config_path()
    _write_pay_config(cfg, {
        "enabled": True,
        "api_key": "secret",
        "gost_listen_port": 18898,
    })

    class SuccessClient:
        def __init__(self, api_key, timeout_s=30, **kwargs):
            pass

        def get_current_proxy(self):
            return {
                "proxy_address": "proxy.example",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "country_code": "US",
            }

    monkeypatch.setattr(gost_manager.s, "PAY_CONFIG_PATH", cfg)
    monkeypatch.setattr(gost_manager, "_port_listening", lambda port: False)
    monkeypatch.setattr(gost_manager, "_WebshareClient", SuccessClient)
    monkeypatch.setattr(gost_manager, "_swap_gost_relay", lambda *args, **kwargs: None)

    assert gost_manager.ensure_gost_alive() is True
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["webshare"]["last_proxy"] == {
        "proxy_address": "proxy.example",
        "port": 8080,
        "username": "user",
        "password": "pass",
        "country_code": "US",
    }


def test_ensure_gost_retries_webshare_api_via_detected_proxy_after_direct_timeout(monkeypatch):
    cfg = _temp_config_path()
    _write_pay_config(cfg, {
        "enabled": True,
        "api_key": "secret",
        "gost_listen_port": 18898,
    })
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

    monkeypatch.setattr(gost_manager.s, "PAY_CONFIG_PATH", cfg)
    monkeypatch.setattr(gost_manager, "_port_listening", lambda port: False)
    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(gost_manager, "_detect_windows_host_ip", lambda: "192.168.0.88")
    monkeypatch.setattr(gost_manager, "_detect_wsl_gateway_ip", lambda: "192.168.0.1")
    monkeypatch.setattr(gost_manager._sock, "create_connection", fake_create_connection)
    monkeypatch.setattr(gost_manager, "_WebshareClient", FakeClient)
    monkeypatch.setattr(gost_manager, "_swap_gost_relay", lambda *args, **kwargs: calls.append(("swap", args, kwargs)))

    assert gost_manager.ensure_gost_alive() is True
    assert ("client", "secret", 8, "") in calls
    assert ("client", "secret", 8, "http://192.168.0.88:7897") in calls
    assert calls[-1][0] == "swap"
    assert calls[-1][1][:4] == ("proxy.example", 8080, "user", "pass")


def test_ensure_gost_does_not_probe_retry_proxy_when_direct_webshare_lookup_works(monkeypatch):
    cfg = _temp_config_path()
    _write_pay_config(cfg, {
        "enabled": True,
        "api_key": "secret",
        "gost_listen_port": 18898,
    })
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

    monkeypatch.setattr(gost_manager.s, "PAY_CONFIG_PATH", cfg)
    monkeypatch.setattr(gost_manager, "_port_listening", lambda port: False)
    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(
        gost_manager,
        "_detect_host_outbound_proxy",
        lambda: (_ for _ in ()).throw(AssertionError("should not probe retry proxy")),
    )
    monkeypatch.setattr(gost_manager, "_WebshareClient", SuccessClient)
    monkeypatch.setattr(gost_manager, "_swap_gost_relay", lambda *args, **kwargs: calls.append(("swap", args, kwargs)))

    assert gost_manager.ensure_gost_alive() is True
    assert calls[0] == ("client", "secret", 8, "")
    assert calls[-1][0] == "swap"


def test_resolve_outbound_proxy_uses_adb_host_ip_before_wsl_gateway(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", "1")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    attempts = []

    class FakeConn:
        def close(self):
            pass

    def fake_create_connection(endpoint, timeout=1):
        attempts.append(endpoint)
        if endpoint == ("192.168.0.88", 7897):
            return FakeConn()
        raise OSError("closed")

    monkeypatch.setattr(gost_manager, "_detect_windows_host_ip", lambda: "192.168.0.88")
    monkeypatch.setattr(gost_manager._sock, "create_connection", fake_create_connection)

    assert gost_manager._resolve_outbound_proxy() == "http://192.168.0.88:7897"
    assert attempts[0] == ("192.168.0.88", 7897)


def test_resolve_outbound_proxy_does_not_probe_host_proxy_by_default(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("GPT_PAY_AUTO_DETECT_HOST_PROXY", raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(
        gost_manager,
        "_detect_windows_host_ip",
        lambda: (_ for _ in ()).throw(AssertionError("should not probe host IP")),
    )

    assert gost_manager._resolve_outbound_proxy() == ""


def test_resolve_outbound_proxy_ignores_env_proxy_by_default(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://192.168.0.1:7897")
    monkeypatch.delenv("GPT_PAY_USE_ENV_PROXY", raising=False)

    assert gost_manager._resolve_outbound_proxy() == ""


def test_resolve_outbound_proxy_allows_explicit_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://192.168.0.1:7897")
    monkeypatch.setenv("GPT_PAY_USE_ENV_PROXY", "1")

    assert gost_manager._resolve_outbound_proxy() == "http://192.168.0.1:7897"
