"""runner 辅助函数：命令行构建 + GoPay OTP 辅助。

从 runner.py 提取，避免主文件超出行数限制。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import settings as s


def build_cmd(mode: str, paypal: bool, batch: int, workers: int, self_dealer: int,
              register_only: bool, pay_only: bool, gopay: bool = False,
              gopay_otp_file: str = "", count: int = 0,
              pay_only_email: str = "") -> list[str]:
    """根据参数拼出最终 pipeline 命令行。"""
    cmd = ["xvfb-run", "-a", "python", "-u", "pipeline.py",
           "--config", str(s.PAY_CONFIG_PATH)]
    if mode in ("free_register", "free_backfill_rt"):
        if mode == "free_register":
            cmd.append("--free-register")
            if count > 0:
                cmd.extend(["--count", str(count)])
        else:
            cmd.append("--free-backfill-rt")
        return cmd
    if gopay:
        cmd.append("--gopay")
        if gopay_otp_file:
            cmd.extend(["--gopay-otp-file", gopay_otp_file])
    elif paypal:
        cmd.append("--paypal")
    if mode == "daemon":
        cmd.append("--daemon")
    elif mode == "self_dealer":
        cmd.extend(["--self-dealer", str(self_dealer)])
    elif mode == "batch":
        cmd.extend(["--batch", str(batch), "--workers", str(workers)])
    if register_only:
        cmd.append("--register-only")
    elif pay_only:
        cmd.append("--pay-only")
        if pay_only_email:
            cmd.extend(["--pay-only-email", pay_only_email])
    return cmd


def read_gopay_otp_source() -> str:
    """读取导出配置中的 gopay.otp.source 值。"""
    try:
        cfg = json.loads(s.PAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "auto"
    gp = cfg.get("gopay") or {}
    otp = gp.get("otp") or gp.get("otp_provider") or {}
    if not isinstance(otp, dict):
        return "auto"
    return str(otp.get("source") or otp.get("type") or "auto").strip().lower()


def gopay_auto_otp_enabled() -> bool:
    """Return True when config has a non-manual gopay.otp provider.

    Legacy helper kept for old tests/tools.
    """
    try:
        cfg = json.loads(s.PAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    gp = cfg.get("gopay") or {}
    if not isinstance(gp, dict):
        return False
    otp = gp.get("otp") or gp.get("otp_provider") or {}
    if not isinstance(otp, dict):
        return False
    source = str(otp.get("source") or otp.get("type") or "auto").strip().lower()
    if source in ("", "manual", "cli", "stdin"):
        return False
    has_url = bool((otp.get("url") or otp.get("relay_url") or "").strip())
    has_path = bool(
        (otp.get("path") or otp.get("state_file") or otp.get("log_file") or "").strip()
    )
    has_command = bool(otp.get("command") or otp.get("cmd"))
    if source in ("http", "https", "relay", "whatsapp_http", "wa_http"):
        return has_url
    if source in ("file", "state_file", "log", "whatsapp_file", "wa_file"):
        return has_path
    if source in ("command", "cmd"):
        return has_command
    if source == "auto":
        return has_url or has_path or has_command
    return False


def detect_otp_wait_target(line: str) -> tuple[str, Optional[Path]]:
    """Return (kind, path) from GoPay OTP wait markers."""
    if "GOPAY_OTP_REQUEST" in line:
        m = re.search(r"\bpath=(.+?)\s*$", line)
        if m:
            return "file", Path(m.group(1).strip().strip("'\""))
        return "file", None

    m = re.search(
        r"\[gopay\]\s+waiting WhatsApp OTP from file:\s*(.+?)\s*$", line
    )
    if m:
        return "file", Path(m.group(1).strip().strip("'\""))

    if re.search(r"\[gopay\]\s+waiting WhatsApp OTP from relay:", line):
        return "db", None
    return "", None
