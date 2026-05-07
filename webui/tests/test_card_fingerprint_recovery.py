import importlib.util
import requests
import sys
import types
from pathlib import Path


def _load_card_module():
    repo_root = Path(__file__).resolve().parents[2]
    card_path = repo_root / "CTF-pay" / "card.py"
    spec = importlib.util.spec_from_file_location("ctf_pay_card_fingerprint_for_test", card_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_register_fingerprint_recovers_gost_and_retries_proxy_timeout(monkeypatch):
    card = _load_card_module()
    monkeypatch.setattr(card, "_log", lambda _line: None)
    recovery_calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeHttp:
        def __init__(self):
            self.posts = []

        def post(self, url, data=None, headers=None, timeout=None):
            self.posts.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
            if len(self.posts) == 1:
                raise requests.exceptions.ConnectTimeout("Connection to m.stripe.com timed out")
            if len(self.posts) == 2:
                return FakeResponse({
                    "guid": "guid-from-retry",
                    "muid": "muid-from-retry",
                    "sid": "sid-from-retry",
                })
            return FakeResponse({})

    def recover_once(exc):
        recovery_calls.append(type(exc).__name__)
        return True

    http = FakeHttp()
    guid, muid, sid = card.register_fingerprint(http, recovery_hook=recover_once)

    assert recovery_calls == ["ConnectTimeout"]
    assert len(http.posts) == 5
    assert (guid, muid, sid) == ("guid-from-retry", "muid-from-retry", "sid-from-retry")


def test_register_fingerprint_does_not_recover_non_proxy_error(monkeypatch):
    card = _load_card_module()
    monkeypatch.setattr(card, "_log", lambda _line: None)
    monkeypatch.setattr(
        card,
        "_gen_fingerprint",
        lambda: ("fallback-guid", "fallback-muid", "fallback-sid"),
    )
    recovery_calls = []

    class FakeHttp:
        def post(self, *args, **kwargs):
            raise ValueError("bad fingerprint payload")

    guid, muid, sid = card.register_fingerprint(
        FakeHttp(),
        recovery_hook=lambda exc: recovery_calls.append(exc) or True,
    )

    assert recovery_calls == []
    assert (guid, muid, sid) == ("fallback-guid", "fallback-muid", "fallback-sid")


def test_recover_gost_for_proxy_failure_calls_pipeline_ensure_when_enabled(monkeypatch):
    card = _load_card_module()
    logs = []
    calls = []
    cfg = {"webshare": {"enabled": True, "api_key": "secret"}}

    def fake_ensure_gost_alive(received_cfg, **kwargs):
        calls.append({"cfg": received_cfg, "kwargs": kwargs})
        return True

    monkeypatch.setattr(card, "_log", logs.append)
    monkeypatch.setitem(
        sys.modules,
        "pipeline",
        types.SimpleNamespace(_ensure_gost_alive=fake_ensure_gost_alive),
    )

    ok = card._recover_gost_for_proxy_failure(cfg, config_path="/tmp/card.json")

    assert ok is True
    assert calls == [{"cfg": cfg, "kwargs": {"cfg_path": "/tmp/card.json"}}]
    assert all("secret" not in line for line in logs)
