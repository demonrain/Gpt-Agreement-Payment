"""ADB WhatsApp OTP Provider。

通过 ADB 读取 Android 设备/模拟器的 WhatsApp OTP（GoPay 验证码）。
策略: 通知栏 dumpsys 优先 → UI 自动化回退。
前置: 设备已连接、WhatsApp 已安装并登录。
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Callable, Optional

_DEFAULT_OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

# 强匹配：必须包含 "gopay" / "go-pay"，基本可以确认是 GoPay 的 OTP 通知
_GOPAY_KW = re.compile(r"gopay|go[\s\-]?pay", re.IGNORECASE)

# 弱匹配：通用 OTP 相关关键词（回退用）
_OTP_KW = re.compile(
    r"verif|kode|code|otp|one.?time|sandi",
    re.IGNORECASE,
)


def _adb_cmd(serial: str, *args: str) -> list[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return cmd


def _shell(serial: str, *args: str, timeout: int = 10) -> str:
    """执行 adb shell 命令并返回 stdout，失败返回空字符串。"""
    try:
        r = subprocess.run(
            _adb_cmd(serial, "shell", *args),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


# --------------- 策略 1: 通知栏 ---------------

def _dump_notifications(serial: str) -> str:
    return _shell(serial, "dumpsys", "notification", "--noredact")


def _collect_wa_blocks(dump: str) -> list[list[str]]:
    """从 dumpsys notification 输出中提取所有 WhatsApp 通知块。"""
    wa_blocks: list[list[str]] = []
    current_block: list[str] = []
    in_wa = False
    for line in dump.splitlines():
        low = line.lower()
        if "pkg=com.whatsapp" in low:
            in_wa = True
            current_block = []
            continue
        if in_wa and "pkg=" in low and "com.whatsapp" not in low:
            if current_block:
                wa_blocks.append(current_block)
            in_wa = False
            current_block = []
            continue
        if in_wa:
            current_block.append(line)
    if current_block:
        wa_blocks.append(current_block)
    return wa_blocks


def _extract_wa_otp_from_dump(dump: str, skip: set[str] | None = None) -> Optional[str]:
    """在 dumpsys notification 输出中查找 WhatsApp 通知里的 6 位 OTP。

    两轮匹配：
      1. 强匹配 — 同一通知块内同时出现 "gopay" 和 6 位数字
      2. 弱匹配 — 同一行包含通用 OTP 关键词和 6 位数字（回退）

    skip: 已见 OTP 集合，跳过这些不返回。
    """
    _skip = skip or set()
    wa_blocks = _collect_wa_blocks(dump)

    # --- 第一轮：强匹配（同一块内含 "gopay" + 6 位数字） ---
    candidates: list[str] = []
    for block in wa_blocks:
        block_text = "\n".join(block)
        if not _GOPAY_KW.search(block_text):
            continue
        for m in _DEFAULT_OTP_RE.finditer(block_text):
            if m.group(1) not in _skip:
                candidates.append(m.group(1))
    if candidates:
        return candidates[-1]

    # --- 第二轮：弱匹配（同一行含通用 OTP 关键词 + 6 位数字） ---
    candidates = []
    for block in wa_blocks:
        for line in block:
            if _OTP_KW.search(line):
                for m in _DEFAULT_OTP_RE.finditer(line):
                    if m.group(1) not in _skip:
                        candidates.append(m.group(1))
    if candidates:
        return candidates[-1]

    return None


def _extract_all_wa_otps_from_dump(dump: str) -> set[str]:
    """提取 dump 中所有 WhatsApp 通知里的 6 位数字（用于预扫描标记旧 OTP）。"""
    result: set[str] = set()
    for block in _collect_wa_blocks(dump):
        block_text = "\n".join(block)
        for m in _DEFAULT_OTP_RE.finditer(block_text):
            result.add(m.group(1))
    return result


# --------------- 策略 2: uiautomator dump 回退 ---------------

_UI_DUMP_PATH = "/sdcard/_wa_ui_dump.xml"


def _dump_whatsapp_ui(serial: str) -> Optional[str]:
    """将 WhatsApp 拉到前台并 dump UI 层级，返回 XML 文本。"""
    # 用 intent 打开 WhatsApp 主界面
    _shell(serial, "am", "start", "-n", "com.whatsapp/.Main", timeout=5)
    time.sleep(1.5)

    # dump 当前界面的 UI 层级
    _shell(serial, "uiautomator", "dump", _UI_DUMP_PATH, timeout=10)
    xml = _shell(serial, "cat", _UI_DUMP_PATH, timeout=5)

    # 读完立即按 Home 回到后台，避免影响后续通知
    _press_home(serial)
    return xml or None


def _extract_otp_from_ui_xml(xml: str, skip: set[str] | None = None) -> Optional[str]:
    """从 uiautomator dump 的 XML 中提取符合关键词的 6 位 OTP。

    XML 格式: <node ... text="Your GoPay code is 123456" .../>

    两轮匹配：
      1. 强匹配 — text 同时包含 "gopay" 和 6 位数字
      2. 弱匹配 — text 包含通用 OTP 关键词和 6 位数字

    skip: 已见 OTP 集合，跳过这些不返回。
    """
    _skip = skip or set()
    texts = [m.group(1) for m in re.finditer(r'text="([^"]*)"', xml) if m.group(1)]

    # 强匹配：text 含 "gopay" 且含 6 位数字
    for text in texts:
        if _GOPAY_KW.search(text):
            for otp_m in _DEFAULT_OTP_RE.finditer(text):
                if otp_m.group(1) not in _skip:
                    return otp_m.group(1)

    # 弱匹配：text 含 OTP 关键词且含 6 位数字
    for text in texts:
        if _OTP_KW.search(text) and len(text) < 120:
            for otp_m in _DEFAULT_OTP_RE.finditer(text):
                if otp_m.group(1) not in _skip:
                    return otp_m.group(1)

    return None


# --------------- 通用工具 ---------------

def _press_home(serial: str) -> None:
    """按 Home 键将前台 App 推到后台。"""
    _shell(serial, "input", "keyevent", "3", timeout=3)


def _dismiss_wa_notifications(serial: str) -> None:
    """清除 WhatsApp 通知避免重复读取。"""
    try:
        subprocess.run(
            _adb_cmd(serial, "shell", "service", "call", "notification", "1"),
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


# --------------- 主入口 ---------------

_UI_FALLBACK_AFTER = 5  # 通知栏连续失败 N 次后启用 UI 回退


def _verify_device(serial: str, log: Callable[[str], None]) -> bool:
    """验证 ADB 设备可达，对 IP:PORT 格式自动执行 adb connect。"""
    if re.match(r"\d+\.\d+\.\d+\.\d+:\d+", serial):
        try:
            r = subprocess.run(_adb_cmd("", "connect", serial),
                               capture_output=True, text=True, timeout=10)
            if "connected" in r.stdout.lower():
                log(f"[gopay] ADB: connected to {serial}")
                return True
            log(f"[gopay] ADB: connect {serial} → {r.stdout.strip()}")
        except Exception as e:
            log(f"[gopay] ADB: connect {serial} failed: {e}")
    if "adb_ok" in _shell(serial, "echo", "adb_ok", timeout=5):
        return True
    log(f"[gopay] ADB: device {serial} unreachable")
    return False


def adb_otp_provider(
    serial: str = "emulator-5554",
    timeout: float = 300.0,
    interval: float = 3.0,
    pre_scan: bool = True,
    log: Callable[[str], None] = print,
) -> Callable[[], str]:
    """工厂函数: 返回一个阻塞式 Callable，轮询 ADB 获取 WhatsApp OTP。

    执行流程:
      1. 验证设备可达（IP:PORT 格式自动 adb connect）
      2. 按 Home 键将 WhatsApp 推到后台（确保新消息产生通知）
      3. 轮询 dumpsys notification 读取通知栏
      4. 如果连续 N 轮读不到，尝试 uiautomator dump 从 WhatsApp 聊天 UI 提取
      5. 两种策略交替执行直到超时
    """

    seen: set[str] = set()
    ui_seen: set[str] = set()
    prepared = False

    def prepare() -> None:
        nonlocal prepared
        if not _verify_device(serial, log):
            raise RuntimeError(f"ADB device {serial} unreachable, abort OTP polling")

        _press_home(serial)
        time.sleep(0.5)

        log("[gopay] ADB: pre-scanning notifications...")
        pre_dump = _dump_notifications(serial)
        if pre_dump:
            seen.update(_extract_all_wa_otps_from_dump(pre_dump))
        _dismiss_wa_notifications(serial)
        pre_xml = _dump_whatsapp_ui(serial)
        if pre_xml:
            for m in _DEFAULT_OTP_RE.finditer(pre_xml):
                ui_seen.add(m.group(1))
        if seen:
            log(f"[gopay] ADB: marked {len(seen)} old OTP(s), cleared notifications")
        if ui_seen:
            log(f"[gopay] ADB: marked {len(ui_seen)} old UI OTP(s)")
        prepared = True

    def provider() -> str:
        log(f"[gopay] waiting WhatsApp OTP from ADB device: {serial}")

        if pre_scan and not prepared:
            prepare()
        else:
            if not _verify_device(serial, log):
                raise RuntimeError(f"ADB device {serial} unreachable, abort OTP polling")
            _press_home(serial)
            time.sleep(0.5)

        log("[gopay] ADB: polling started")

        deadline = time.time() + timeout
        notify_miss = 0

        while time.time() < deadline:
            dump = _dump_notifications(serial)
            otp = _extract_wa_otp_from_dump(dump, skip=seen) if dump else None
            if otp:
                seen.add(otp)
                log(f"[gopay] ADB: OTP={otp} (from notification)")
                _dismiss_wa_notifications(serial)
                return otp

            notify_miss += 1

            if notify_miss >= _UI_FALLBACK_AFTER:
                xml = _dump_whatsapp_ui(serial)
                if xml:
                    all_skip = seen | ui_seen
                    otp = _extract_otp_from_ui_xml(xml, skip=all_skip)
                    if otp:
                        seen.add(otp)
                        ui_seen.add(otp)
                        log(f"[gopay] ADB: OTP={otp} (from UI dump)")
                        return otp

            remaining = int(deadline - time.time())
            if notify_miss > 0 and notify_miss % 20 == 0:
                log(f"[gopay] ADB: still waiting OTP... ({remaining}s remaining)")

            time.sleep(interval)

        raise TimeoutError(f"ADB WhatsApp OTP timeout after {timeout}s (device={serial})")

    setattr(provider, "prepare", prepare)
    return provider
