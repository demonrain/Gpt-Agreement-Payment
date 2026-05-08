import json
import os
import sys
import types

import pipeline
from webui.backend.db import get_db


def _reset_db(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBUI_DATA_DIR", str(tmp_path))
    db = get_db()
    db.clear_runtime_data()
    return db


def test_pay_only_selects_latest_registered_unpaid_account(tmp_path, monkeypatch):
    db = _reset_db(tmp_path, monkeypatch)

    for row in [
        {
            "ts": "2026-05-03T01:00:00+00:00",
            "email": "paid@example.com",
            "session_token": "sess-paid",
            "access_token": "at-paid",
            "device_id": "dev-paid",
        },
        {
            "ts": "2026-05-03T02:00:00+00:00",
            "email": "retry@example.com",
            "session_token": "sess-retry",
            "access_token": "at-retry",
            "device_id": "dev-retry",
        },
        {
            "ts": "2026-05-03T03:00:00+00:00",
            "email": "no-auth@example.com",
            "session_token": "",
            "access_token": "",
            "device_id": "dev-noauth",
        },
    ]:
        db.add_registered_account(row)
    db.add_pipeline_result({
        "registration": {"status": "ok", "email": "paid@example.com"},
        "payment": {"status": "succeeded", "email": "paid@example.com"},
    })
    db.add_pipeline_result({
        "registration": {"status": "ok", "email": "retry@example.com"},
        "payment": {"status": "error", "email": "retry@example.com", "error": "OTP timeout"},
    })

    selected = pipeline._select_recent_registered_account_for_pay_only()
    assert selected is not None
    assert selected["email"] == "retry@example.com"
    assert selected["session_token"] == "sess-retry"
    assert selected["access_token"] == "at-retry"


def test_pay_only_treats_already_paid_error_as_consumed(tmp_path, monkeypatch):
    db = _reset_db(tmp_path, monkeypatch)

    db.add_registered_account({"email": "older@example.com", "session_token": "sess-older", "access_token": ""})
    db.add_registered_account({"email": "latest@example.com", "session_token": "sess-latest", "access_token": ""})
    db.add_pipeline_result({
        "registration": {"status": "ok", "email": "latest@example.com"},
        "payment": {
            "status": "error",
            "email": "latest@example.com",
            "error": '生成 fresh checkout 失败: modern [400]: {"detail":"User is already paid"}',
        },
    })

    selected = pipeline._select_recent_registered_account_for_pay_only()
    assert selected is not None
    assert selected["email"] == "older@example.com"


def test_pay_only_success_imports_cpa_with_plus_tag(tmp_path, monkeypatch):
    db = _reset_db(tmp_path, monkeypatch)
    card_config = tmp_path / "config.paypal.json"

    db.add_registered_account({
        "email": "retry@example.com",
        "session_token": "sess-retry",
        "access_token": "at-retry",
        "device_id": "dev-retry",
    })
    card_config.write_text(json.dumps({
        "fresh_checkout": {"plan": {"plan_name": "chatgptplusplan"}},
        "cpa": {
            "enabled": True,
            "base_url": "https://cpa.example.com",
            "admin_key": "adm",
            "oauth_client_id": "app_test",
            "plan_tag": "team",
        },
    }), encoding="utf-8")

    calls = []

    def fake_pay(*args, **kwargs):
        return {
            "status": "succeeded",
            "raw": {
                "session_id": "cs_test",
                "chatgpt_email": "retry@example.com",
            },
        }

    def fake_cpa(email, sid, cpa_cfg, **kwargs):
        calls.append((email, sid, cpa_cfg, kwargs))
        return "ok"

    monkeypatch.setattr(pipeline, "pay", fake_pay)
    monkeypatch.setattr(pipeline, "_cpa_import_after_team", fake_cpa)

    result = pipeline.pay_only(str(card_config), use_gopay=True)

    assert result["status"] == "succeeded"
    assert calls
    email, sid, cpa_cfg, kwargs = calls[0]
    assert email == "retry@example.com"
    assert sid == "cs_test"
    assert cpa_cfg["plan_tag"] == "plus"
    rows = get_db().iter_pipeline_results()
    assert rows[-1]["cpa_import"] == "ok"


def test_pay_only_ensures_gost_after_rotation_before_retry(tmp_path, monkeypatch):
    db = _reset_db(tmp_path, monkeypatch)
    card_config = tmp_path / "config.paypal.json"

    db.add_registered_account({
        "email": "retry@example.com",
        "session_token": "sess-retry",
        "access_token": "at-retry",
        "device_id": "dev-retry",
    })
    card_config.write_text(json.dumps({
        "webshare": {"enabled": True, "api_key": "secret"},
    }), encoding="utf-8")

    events = []

    def fake_pay(*args, **kwargs):
        events.append("pay")
        if events.count("pay") == 1:
            raise pipeline.PaymentError("network failed")
        return {"status": "succeeded", "raw": {"session_id": "cs_test"}}

    monkeypatch.setattr(pipeline, "pay", fake_pay)
    monkeypatch.setattr(pipeline, "_rotate_webshare_ip", lambda cfg: events.append("rotate") or {"proxy_address": "proxy.example"})
    monkeypatch.setattr(pipeline, "_ensure_gost_alive", lambda cfg, **kwargs: events.append("ensure") or True)
    monkeypatch.setattr(pipeline, "_cpa_import_after_team", lambda *args, **kwargs: "skipped")
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)

    result = pipeline.pay_only(str(card_config), use_gopay=True)

    assert result["status"] == "succeeded"
    assert events[:4] == ["pay", "rotate", "ensure", "pay"]


def test_cpa_import_falls_back_to_access_token_without_refresh_token(tmp_path, monkeypatch):
    db = _reset_db(tmp_path, monkeypatch)
    db.add_registered_account({
        "email": "fallback@example.com",
        "access_token": "eyJhbGciOiJub25lIn0.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdF8xMjMifSwiZXhwIjoyNTM0MDk0NDAwfQ.sig",
    })
    monkeypatch.setattr(pipeline, "_find_latest_refresh_token_for_email", lambda *args, **kwargs: "")

    fake_calls = []

    class FakeResponse:
        status_code = 200
        text = ""

    class FakeSession:
        def __init__(self, *args, **kwargs):
            self.proxies = {}
            self.trust_env = False

        def post(self, url, params=None, json=None, headers=None, timeout=None):
            fake_calls.append({"url": url, "params": params, "json": json, "headers": headers, "timeout": timeout})
            return FakeResponse()

    fake_requests = types.ModuleType("curl_cffi.requests")
    fake_requests.Session = lambda impersonate=None: FakeSession()
    fake_pkg = types.ModuleType("curl_cffi")
    fake_pkg.requests = fake_requests
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_pkg)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_requests)

    status = pipeline._cpa_import_after_team(
        "fallback@example.com",
        "cs_test",
        {
            "enabled": True,
            "base_url": "https://cpa.example.com",
            "admin_key": "secret-admin-key",
            "oauth_client_id": "app_test_client",
            "plan_tag": "team",
            "free_plan_tag": "free",
        },
    )

    assert status == "ok"
    assert fake_calls
    body = fake_calls[0]["json"]
    assert body["email"] == "fallback@example.com"
    assert body["access_token"].startswith("eyJhbGciOiJub25lIn0.")
    assert body["refresh_token"] == ""
    assert body["account_id"] == "acct_123"


def test_free_backfill_rt_loop_exits_when_lock_already_held(tmp_path, monkeypatch, capsys):
    db = _reset_db(tmp_path, monkeypatch)
    db.add_registered_account({
        "email": "locked@example.com",
        "password": "pw",
        "device_id": "dev",
    })
    card_config = tmp_path / "config.paypal.json"
    card_config.write_text(json.dumps({
        "mail": {},
        "cpa": {},
    }), encoding="utf-8")
    lock_path = tmp_path / "free-backfill.lock"
    lock_handle = open(lock_path, "a+", encoding="utf-8")

    try:
        if os.name == "nt":
            import msvcrt

            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        monkeypatch.setattr(pipeline, "_oauth_lock_path", lambda _name: lock_path)
        monkeypatch.setattr(
            pipeline,
            "_exchange_rt_with_classification",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("should not run while lock is held")
            ),
        )

        pipeline.free_backfill_rt_loop(str(card_config))
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()

    assert "已有 free-backfill-rt 正在运行" in capsys.readouterr().out


def test_free_backfill_rt_loop_exits_when_existing_process_detected(tmp_path, monkeypatch, capsys):
    db = _reset_db(tmp_path, monkeypatch)
    db.add_registered_account({
        "email": "running@example.com",
        "password": "pw",
        "device_id": "dev",
    })
    card_config = tmp_path / "config.paypal.json"
    card_config.write_text(json.dumps({
        "mail": {},
        "cpa": {},
    }), encoding="utf-8")
    monkeypatch.setattr(pipeline, "_oauth_lock_path", lambda _name: tmp_path / "free-backfill.lock")
    monkeypatch.setattr(
        pipeline,
        "_find_running_free_backfill_processes",
        lambda: [{"pid": "22622", "cmd": "python -u pipeline.py --free-backfill-rt"}],
    )
    monkeypatch.setattr(
        pipeline,
        "_exchange_rt_with_classification",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not run while an older process is active")
        ),
    )

    pipeline.free_backfill_rt_loop(str(card_config))

    out = capsys.readouterr().out
    assert "已有 free-backfill-rt 进程正在运行" in out
    assert "22622" in out


def test_find_running_free_backfill_processes_ignores_current_xvfb_parent(monkeypatch):
    proc_rows = {
        30498: (303, "/bin/sh /usr/bin/xvfb-run -a python -u pipeline.py --config cfg --free-backfill-rt"),
        30501: (30498, "python -u pipeline.py --config cfg --free-backfill-rt"),
    }
    monkeypatch.setattr(pipeline.os, "getpid", lambda: 30501)
    monkeypatch.setattr(pipeline, "_iter_linux_process_cmds", lambda: [
        {"pid": str(pid), "ppid": str(ppid), "cmd": cmd}
        for pid, (ppid, cmd) in proc_rows.items()
    ])
    monkeypatch.setattr(pipeline, "_linux_ancestor_pids", lambda _pid: {30498, 303})

    running = pipeline._find_running_free_backfill_processes()

    assert running == []


def test_exchange_rt_sets_run_id_env(monkeypatch):
    env_values = []

    class FakeCardModule:
        def _exchange_refresh_token_with_session(self, **_kwargs):
            env_values.append(os.environ.get("RT_RUN_ID", ""))
            return "rt_ok"

    monkeypatch.setitem(sys.modules, "card", FakeCardModule())

    rt, fail = pipeline._exchange_rt_with_classification(
        "buyer@example.com",
        "pw",
        {},
        "",
        run_id="free-backfill:12345",
    )

    assert rt == "rt_ok"
    assert fail == ""
    assert env_values == ["free-backfill:12345"]
    assert "RT_RUN_ID" not in os.environ
