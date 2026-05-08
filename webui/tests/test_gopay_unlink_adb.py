import importlib.util
from pathlib import Path
from xml.sax.saxutils import escape


def _load_unlink_module():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "CTF-pay" / "gopay_unlink_adb.py"
    spec = importlib.util.spec_from_file_location("gopay_unlink_adb_for_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _node(desc, bounds="[100,100][200,200]", klass="android.widget.TextView"):
    return (
        f'<node class="{klass}" text="" content-desc="{escape(desc)}" '
        f'resource-id="" bounds="{bounds}" />'
    )


def _xml(*nodes):
    return '<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"


def test_gopay_unlink_retries_when_openai_still_visible_after_first_confirm(monkeypatch):
    mod = _load_unlink_module()
    linked_apps = _xml(
        _node("OpenAI", "[100,100][300,180]"),
        _node("Unlink", "[700,100][850,180]", "android.widget.Button"),
    )
    confirm_dialog = _xml(
        _node("Unlink OpenAI from GoPay?", "[100,600][800,700]"),
        _node("Unlink", "[100,1400][800,1550]", "android.widget.Button"),
    )
    no_apps = _xml(_node("No app linked", "[100,500][800,600]"))
    states = iter(
        [
            _xml(_node("Profile", "[700,1450][900,1600]")),
            _xml(_node("Account & app settings", "[100,750][800,850]")),
            _xml(_node("Linked apps", "[100,450][800,600]")),
            linked_apps,
            confirm_dialog,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
            confirm_dialog,
            no_apps,
        ]
    )
    taps = []
    now = [0.0]

    monkeypatch.setattr(mod, "_shell", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mod, "_dump_ui", lambda _serial: next(states))
    monkeypatch.setattr(mod, "_tap", lambda _serial, x, y: taps.append((x, y)))
    monkeypatch.setattr(mod, "_back", lambda _serial: None)
    monkeypatch.setattr(mod.time, "time", lambda: now[0])
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    result = mod.gopay_unlink_openai(serial="device-1", log=lambda _line: None)

    assert result["ok"] is True
    assert result["attempts"] == 2
    assert len(taps) >= 5


def test_gopay_unlink_final_recheck_restarts_app_before_failure(monkeypatch):
    mod = _load_unlink_module()
    linked_apps = _xml(
        _node("OpenAI", "[100,100][300,180]"),
        _node("Unlink", "[700,100][850,180]", "android.widget.Button"),
    )
    confirm_dialog = _xml(
        _node("Unlink OpenAI from GoPay?", "[100,600][800,700]"),
        _node("Unlink", "[100,1400][800,1550]", "android.widget.Button"),
    )
    states = [
        _xml(_node("Profile", "[700,1450][900,1600]")),
        _xml(_node("Account & app settings", "[100,750][800,850]")),
        _xml(_node("Linked apps", "[100,450][800,600]")),
    ]
    for _ in range(3):
        states.extend([
            linked_apps,
            confirm_dialog,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
            linked_apps,
        ])
    states.extend([
        _xml(_node("Profile", "[700,1450][900,1600]")),
        _xml(_node("Account & app settings", "[100,750][800,850]")),
        _xml(_node("Linked apps", "[100,450][800,600]")),
    ])
    states.append(linked_apps)
    state_iter = iter(states)
    shell_calls = []
    now = [0.0]

    def fake_shell(_serial, *args, **_kwargs):
        shell_calls.append(args)
        return ""

    monkeypatch.setattr(mod, "_shell", fake_shell)
    monkeypatch.setattr(mod, "_dump_ui", lambda _serial: next(state_iter))
    monkeypatch.setattr(mod, "_tap", lambda *_args: None)
    monkeypatch.setattr(mod, "_back", lambda _serial: None)
    monkeypatch.setattr(mod.time, "time", lambda: now[0])
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    result = mod.gopay_unlink_openai(serial="device-1", log=lambda _line: None)

    assert result["ok"] is False
    assert sum(1 for call in shell_calls if call[:2] == ("am", "force-stop")) >= 2
    assert sum(1 for call in shell_calls if call[:2] == ("am", "start")) >= 2
    assert any("final_recheck" in line for line in result["message"].split())
