from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "adb_otp_provider_mod",
    ROOT / "CTF-pay" / "adb_otp_provider.py",
)
adb_otp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adb_otp)  # type: ignore[union-attr]


def _wa_dump(code: str) -> str:
    return "\n".join([
        "NotificationRecord(pkg=com.whatsapp user=UserHandle{0})",
        f'  android.title=GoPay',
        f'  android.text=Kode verifikasi GoPay Anda adalah {code}',
    ])


def _wa_ui_xml(*codes: str) -> str:
    return "\n".join(
        f'<node index="{idx}" text="Kode verifikasi GoPay Anda adalah {code}" />'
        for idx, code in enumerate(codes)
    )


def test_extract_whatsapp_dump_prefers_latest_candidate_in_block():
    dump = "\n".join([
        "NotificationRecord(pkg=com.whatsapp user=UserHandle{0})",
        "  android.text=Kode GoPay lama 111111",
        "  android.bigText=Kode verifikasi GoPay Anda adalah 222222",
    ])

    assert adb_otp._extract_wa_otp_from_dump(dump) == "222222"


def test_adb_provider_persists_returned_codes_between_calls(monkeypatch):
    dumps = iter([
        _wa_dump("111111"),
        _wa_dump("111111"),
        _wa_dump("222222"),
    ])

    monkeypatch.setattr(adb_otp, "_verify_device", lambda serial, log: True)
    monkeypatch.setattr(adb_otp, "_press_home", lambda serial: None)
    monkeypatch.setattr(adb_otp, "_dismiss_wa_notifications", lambda serial: None)
    monkeypatch.setattr(adb_otp, "_dump_notifications", lambda serial: next(dumps))
    monkeypatch.setattr(adb_otp, "_dump_whatsapp_ui", lambda serial: None)
    monkeypatch.setattr(adb_otp.time, "sleep", lambda _s: None)

    provider = adb_otp.adb_otp_provider(
        serial="device",
        timeout=5,
        interval=0,
        pre_scan=False,
        log=lambda _m: None,
    )

    assert provider() == "111111"
    assert provider() == "222222"


def test_adb_provider_pre_scan_can_run_before_consent(monkeypatch):
    dumps = iter([
        _wa_dump("111111"),
        _wa_dump("111111"),
        _wa_dump("222222"),
    ])

    monkeypatch.setattr(adb_otp, "_verify_device", lambda serial, log: True)
    monkeypatch.setattr(adb_otp, "_press_home", lambda serial: None)
    monkeypatch.setattr(adb_otp, "_dismiss_wa_notifications", lambda serial: None)
    monkeypatch.setattr(adb_otp, "_dump_notifications", lambda serial: next(dumps))
    monkeypatch.setattr(adb_otp, "_dump_whatsapp_ui", lambda serial: None)
    monkeypatch.setattr(adb_otp.time, "sleep", lambda _s: None)

    provider = adb_otp.adb_otp_provider(
        serial="device",
        timeout=5,
        interval=0,
        pre_scan=False,
        log=lambda _m: None,
    )
    provider.prepare()

    assert provider() == "222222"


def test_adb_provider_prepare_failure_does_not_hide_polling(monkeypatch):
    monkeypatch.setattr(adb_otp, "_verify_device", lambda serial, log: False)
    provider = adb_otp.adb_otp_provider(
        serial="device",
        timeout=1,
        interval=0,
        pre_scan=False,
        log=lambda _m: None,
    )

    with pytest.raises(RuntimeError):
        provider.prepare()


def test_adb_provider_ui_fallback_returns_code_seen_after_prepare(monkeypatch):
    now = {"value": 1000.0}
    dump_calls = {"count": 0}
    ui_xmls = iter([
        _wa_ui_xml("111111"),
        _wa_ui_xml("111111", "222222"),
    ])

    def fake_time():
        return now["value"]

    def fake_sleep(seconds):
        now["value"] += float(seconds or 0.1)

    def fake_dump_notifications(_serial):
        dump_calls["count"] += 1
        if dump_calls["count"] == 1:
            return _wa_dump("111111")
        return ""

    monkeypatch.setattr(adb_otp, "_verify_device", lambda serial, log: True)
    monkeypatch.setattr(adb_otp, "_press_home", lambda serial: None)
    monkeypatch.setattr(adb_otp, "_dismiss_wa_notifications", lambda serial: None)
    monkeypatch.setattr(adb_otp, "_dump_notifications", fake_dump_notifications)
    monkeypatch.setattr(adb_otp, "_dump_whatsapp_ui", lambda serial: next(ui_xmls))
    monkeypatch.setattr(adb_otp.time, "time", fake_time)
    monkeypatch.setattr(adb_otp.time, "sleep", fake_sleep)

    provider = adb_otp.adb_otp_provider(
        serial="device",
        timeout=5,
        interval=0.1,
        pre_scan=False,
        log=lambda _m: None,
    )
    provider.prepare()

    assert provider() == "222222"
