"""ADB 通知栏 WhatsApp OTP Provider。

通过 ADB 读取 Android 设备/模拟器的通知栏，提取 GoPay 发来的 WhatsApp OTP。

前置条件:
  - Android 设备/模拟器已安装 WhatsApp 并登录
  - ADB 已连接（`adb devices` 可见设备）
  - WhatsApp 通知未被关闭

配置示例:
  "gopay": {
    "otp": {
      "source": "adb",
      "adb_serial": "emulator-5554",
      "timeout": 300,
      "interval": 3
    }
  }
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Callable, Optional

_DEFAULT_OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_WA_KEYWORDS = re.compile(
    r"gopay|go-pay|link|verif|kode|code|otp|one.?time|sandi",
    re.IGNORECASE,
)


def _adb_cmd(serial: str, *args: str) -> list[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return cmd


def _dump_notifications(serial: str) -> str:
    try:
        r = subprocess.run(
            _adb_cmd(serial, "shell", "dumpsys", "notification", "--noredact"),
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _extract_wa_otp_from_dump(dump: str) -> Optional[str]:
    """在 dumpsys notification 输出中查找 WhatsApp 通知里的 6 位 OTP。"""
    in_wa = False
    for line in dump.splitlines():
        low = line.lower()
        if "pkg=com.whatsapp" in low:
            in_wa = True
            continue
        if in_wa and "pkg=" in low and "com.whatsapp" not in low:
            in_wa = False
            continue
        if in_wa and _WA_KEYWORDS.search(line):
            m = _DEFAULT_OTP_RE.search(line)
            if m:
                return m.group(1)
    return None


def _dismiss_wa_notifications(serial: str) -> None:
    """清除 WhatsApp 通知避免重复读取。"""
    try:
        subprocess.run(
            _adb_cmd(serial, "shell", "service", "call", "notification", "1"),
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def adb_otp_provider(
    serial: str = "emulator-5554",
    timeout: float = 300.0,
    interval: float = 3.0,
    log: Callable[[str], None] = print,
) -> Callable[[], str]:
    """工厂函数: 返回一个阻塞式 Callable，轮询 ADB 通知栏获取 WhatsApp OTP。"""

    def provider() -> str:
        log(f"[gopay] waiting WhatsApp OTP from ADB device: {serial}")

        # 先清除旧通知
        _dismiss_wa_notifications(serial)

        deadline = time.time() + timeout
        seen: set[str] = set()

        while time.time() < deadline:
            dump = _dump_notifications(serial)
            if dump:
                otp = _extract_wa_otp_from_dump(dump)
                if otp and otp not in seen:
                    log(f"[gopay] ADB: OTP={otp} (from notification)")
                    _dismiss_wa_notifications(serial)
                    return otp
                if otp:
                    seen.add(otp)
            time.sleep(interval)

        raise TimeoutError(f"ADB WhatsApp OTP timeout after {timeout}s (device={serial})")

    return provider
