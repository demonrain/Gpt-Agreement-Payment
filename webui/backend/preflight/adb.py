"""ADB 设备连接检测 preflight。

检查项：
  1. adb 可执行文件是否在 PATH
  2. 指定设备是否已连接
  3. WhatsApp 是否已安装
  4. WhatsApp 通知栏是否可读取

WSL/Docker 环境自动检测宿主机 IP，替换 127.0.0.1 为可达地址。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from ._common import CheckResult, PreflightResult, aggregate


def _detect_host_ip() -> str | None:
    """WSL/Docker 环境下获取宿主机 IP（用于连接宿主机上的模拟器）。"""
    # WSL2: resolv.conf 中的 nameserver 就是宿主机
    resolv = Path("/etc/resolv.conf")
    if resolv.exists():
        try:
            for line in resolv.read_text().splitlines():
                if line.strip().startswith("nameserver"):
                    ip = line.split()[1]
                    if ip != "127.0.0.1":
                        return ip
        except Exception:
            pass
    # Docker: host.docker.internal
    if os.path.exists("/.dockerenv"):
        return "host.docker.internal"
    return None


_HOST_IP = _detect_host_ip()

# MuMu 模拟器常见默认端口（使用检测到的宿主机 IP 或 127.0.0.1）
_H = _HOST_IP or "127.0.0.1"
KNOWN_EMULATOR_PORTS = {
    "mumu": f"{_H}:7555",
    "mumu12": f"{_H}:16384",
    "ldplayer": "emulator-5554",
    "nox": f"{_H}:62001",
    "bluestacks": f"{_H}:5555",
}


def _run_adb(serial: str, *args: str, timeout: int = 10) -> tuple[int, str, str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", "adb not found"
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except Exception as e:
        return -3, "", str(e)


def check(body: dict) -> PreflightResult:
    serial = str(body.get("adb_serial") or "").strip()
    checks: list[CheckResult] = []

    # 1. adb 是否可用
    adb_path = shutil.which("adb")
    if adb_path:
        checks.append(CheckResult(
            name="adb_binary",
            status="ok",
            message=f"adb 已找到: {adb_path}",
        ))
    else:
        checks.append(CheckResult(
            name="adb_binary",
            status="fail",
            message="adb 不在 PATH 中，请安装 Android SDK Platform-Tools",
        ))
        return aggregate(checks)

    # 2. 尝试连接（对 IP:PORT 格式先 adb connect）
    if serial and re.match(r"\d+\.\d+\.\d+\.\d+:\d+", serial):
        rc, out, err = _run_adb("", "connect", serial)
        if rc == 0 and "connected" in out.lower():
            checks.append(CheckResult(
                name="adb_connect",
                status="ok",
                message=f"adb connect {serial} 成功",
                details=out.strip()[:200],
            ))
        else:
            checks.append(CheckResult(
                name="adb_connect",
                status="warn",
                message=f"adb connect {serial} 结果不确定",
                details=(out + err).strip()[:200],
            ))

    # 3. 设备是否在线
    rc, out, _ = _run_adb("", "devices")
    if rc != 0:
        checks.append(CheckResult(
            name="adb_devices",
            status="fail",
            message="adb devices 命令失败",
        ))
        return aggregate(checks)

    device_lines = [
        l for l in out.strip().splitlines()[1:]
        if l.strip() and "device" in l
    ]
    all_devices = [l.split()[0] for l in device_lines if l.split()]

    if serial:
        found = any(serial in d or d in serial for d in all_devices)
        if found:
            checks.append(CheckResult(
                name="device_online",
                status="ok",
                message=f"设备 {serial} 在线",
                details=f"所有设备: {', '.join(all_devices)}",
            ))
        else:
            checks.append(CheckResult(
                name="device_online",
                status="fail",
                message=f"设备 {serial} 未找到",
                details=f"在线设备: {', '.join(all_devices) or '(无)'}",
            ))
            return aggregate(checks)
    elif all_devices:
        serial = all_devices[0]
        checks.append(CheckResult(
            name="device_online",
            status="ok",
            message=f"自动检测到设备: {serial}",
            details=f"所有设备: {', '.join(all_devices)}",
        ))
    else:
        checks.append(CheckResult(
            name="device_online",
            status="fail",
            message="未检测到任何 ADB 设备",
            details="请确认模拟器已启动且 ADB 调试已开启",
        ))
        return aggregate(checks)

    # 4. WhatsApp 是否已安装
    rc, out, _ = _run_adb(serial, "shell", "pm", "list", "packages", "com.whatsapp")
    wa_installed = "com.whatsapp" in out
    if wa_installed:
        checks.append(CheckResult(
            name="whatsapp_installed",
            status="ok",
            message="WhatsApp 已安装",
        ))
    else:
        checks.append(CheckResult(
            name="whatsapp_installed",
            status="fail",
            message="WhatsApp 未安装，请在模拟器中安装 WhatsApp 并登录",
        ))
        return aggregate(checks)

    # 5. 通知栏读取测试
    rc, out, err = _run_adb(serial, "shell", "dumpsys", "notification", "--noredact")
    if rc == 0 and len(out) > 50:
        wa_notif = "com.whatsapp" in out.lower()
        checks.append(CheckResult(
            name="notification_read",
            status="ok",
            message="通知栏可读取" + ("，检测到 WhatsApp 通知" if wa_notif else "（暂无 WhatsApp 通知）"),
            details=f"dumpsys 输出长度: {len(out)} 字符",
        ))
    else:
        checks.append(CheckResult(
            name="notification_read",
            status="warn",
            message="通知栏读取异常",
            details=(err or out)[:200],
        ))

    return aggregate(checks)


def list_devices() -> dict:
    """列出所有 ADB 设备及其状态。"""
    adb_path = shutil.which("adb")
    if not adb_path:
        return {"ok": False, "error": "adb not in PATH, 请在 WSL 中运行: sudo apt install android-tools-adb", "devices": []}

    rc, out, err = _run_adb("", "devices", "-l")
    if rc != 0:
        return {"ok": False, "error": err[:200], "devices": []}

    devices = []
    for line in out.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            serial = parts[0]
            state = parts[1]
            model = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
            devices.append({
                "serial": serial,
                "state": state,
                "model": model,
            })

    return {
        "ok": True,
        "devices": devices,
        "known_ports": KNOWN_EMULATOR_PORTS,
        "host_ip": _HOST_IP,
        "hint": f"WSL 环境检测到宿主机 IP: {_HOST_IP}，模拟器端口请使用 {_HOST_IP}:<port>" if _HOST_IP else None,
    }
