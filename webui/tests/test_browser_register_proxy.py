import importlib.util
import sys
import types
from pathlib import Path
import requests


def _load_browser_register_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "CTF-reg" / "browser_register.py"
    spec = importlib.util.spec_from_file_location("ctf_reg_browser_register_for_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_proxy_ip_logs_last_error(monkeypatch, caplog):
    mod = _load_browser_register_module()

    def fake_get(*args, **kwargs):
        raise RuntimeError("proxy connection failed")

    monkeypatch.setattr(requests, "get", fake_get)

    with caplog.at_level("WARNING"):
        assert mod._resolve_proxy_ip("socks5h://127.0.0.1:18898") is None

    assert "无法通过代理获取出口 IP，将跳过 geoip" in caplog.text
    assert "proxy connection failed" in caplog.text


def test_browser_register_disables_camoufox_geoip_when_proxy_ip_probe_fails(monkeypatch):
    mod = _load_browser_register_module()
    captured = {}

    class FakePage:
        url = "https://chatgpt.com/"

        def goto(self, *args, **kwargs):
            raise RuntimeError("stop after launch")

    class FakeContext:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_camoufox(**kwargs):
        captured.update(kwargs)
        return FakeContext()

    fake_camoufox_mod = types.ModuleType("camoufox.sync_api")
    fake_camoufox_mod.Camoufox = fake_camoufox
    fake_camoufox_pkg = types.ModuleType("camoufox")
    fake_browserforge_mod = types.ModuleType("browserforge.fingerprints")
    fake_browserforge_mod.Screen = lambda **kwargs: {"screen": kwargs}
    fake_browserforge_pkg = types.ModuleType("browserforge")
    monkeypatch.setitem(sys.modules, "camoufox", fake_camoufox_pkg)
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_camoufox_mod)
    monkeypatch.setitem(sys.modules, "browserforge", fake_browserforge_pkg)
    monkeypatch.setitem(sys.modules, "browserforge.fingerprints", fake_browserforge_mod)
    monkeypatch.setattr(mod, "_resolve_proxy_ip", lambda proxy_url: None)
    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda prefix="": str(Path("output") / "fake-profile"))
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *args, **kwargs: None)

    cfg = types.SimpleNamespace(proxy="socks5h://127.0.0.1:18898")
    mail_provider = types.SimpleNamespace(create_mailbox=lambda: "user@example.com")

    try:
        mod.browser_register(cfg, mail_provider)
    except RuntimeError as e:
        assert "stop after launch" in str(e)

    assert captured["proxy"] == {"server": "socks5://127.0.0.1:18898", "username": "", "password": ""}
    assert captured["geoip"] is False
