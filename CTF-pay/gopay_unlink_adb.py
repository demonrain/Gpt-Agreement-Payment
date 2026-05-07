"""ADB UI 自动化：从 GoPay 取消 OpenAI 关联。

支付成功后，GoPay 会保留 OpenAI 的"已关联应用"记录。
如果不取消关联，下次 linking 可能出现 406 "account already linked"。

本模块通过 ADB 操控 GoPay 应用 UI 来完成自动 Unlink。

导航路径（基于 GoPay App 2026-05 UI）:
  Profile 页 → Account & app settings → Linked apps → OpenAI → Unlink → 确认

重要：GoPay 的 UI 元素全部使用 content-desc 属性（而非 text）。
"""
from __future__ import annotations

import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Callable


def _adb_cmd(serial: str, *args: str) -> list[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return cmd


def _shell(serial: str, *args: str, timeout: float = 15) -> str:
    try:
        r = subprocess.run(
            _adb_cmd(serial, "shell", *args),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _tap(serial: str, x: int, y: int) -> None:
    subprocess.run(
        _adb_cmd(serial, "shell", "input", "tap", str(x), str(y)),
        capture_output=True, timeout=10,
    )


def _back(serial: str) -> None:
    subprocess.run(
        _adb_cmd(serial, "shell", "input", "keyevent", "KEYCODE_BACK"),
        capture_output=True, timeout=10,
    )


def _dump_ui(serial: str) -> str:
    """Dump UI hierarchy XML via uiautomator。"""
    _shell(serial, "uiautomator", "dump", "/sdcard/window_dump.xml", timeout=20)
    return _shell(serial, "cat", "/sdcard/window_dump.xml", timeout=10)


def _find_node(xml_str: str, **attrs) -> dict | None:
    """在 UI XML 中查找匹配属性的第一个节点，返回 bounds 中心坐标。

    attrs 的值可以是 str（子串匹配）或 re.Pattern（正则匹配）。
    """
    if not xml_str:
        return None
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None
    for elem in root.iter("node"):
        matched = True
        for key, pattern in attrs.items():
            val = elem.get(key, "")
            if isinstance(pattern, re.Pattern):
                if not pattern.search(val):
                    matched = False
                    break
            elif pattern not in val:
                matched = False
                break
        if matched:
            bounds = elem.get("bounds", "")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                return {
                    "x": (x1 + x2) // 2,
                    "y": (y1 + y2) // 2,
                    "text": elem.get("text", ""),
                    "content-desc": elem.get("content-desc", ""),
                    "resource-id": elem.get("resource-id", ""),
                }
    return None


def _find_by_desc(xml_str: str, pattern: re.Pattern) -> dict | None:
    """按 content-desc 匹配查找节点（GoPay 的 UI 标签全部在 content-desc 中）。"""
    return _find_node(xml_str, **{"content-desc": pattern})


def _dump_all_descs(xml_str: str) -> list[str]:
    """提取所有非空 content-desc 值（用于调试）。"""
    if not xml_str:
        return []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return []
    descs = []
    for elem in root.iter("node"):
        desc = elem.get("content-desc", "").strip()
        if desc:
            descs.append(desc.replace("\n", " | "))
    return descs


def _tap_node(serial: str, node: dict, log: Callable, label: str) -> None:
    """点击节点并记录日志。"""
    log(f"[unlink] 点击 {label}: ({node['x']}, {node['y']})")
    _tap(serial, node["x"], node["y"])


def _find_openai_linked(xml: str) -> dict | None:
    return _find_by_desc(xml, re.compile(r"(?i)openai|open\s*ai|chatgpt"))


def _find_unlink_button(xml: str) -> dict | None:
    btn = _find_node(xml, **{
        "content-desc": re.compile(r"(?i)^unlink$"),
        "class": "android.widget.Button",
    })
    if btn:
        return btn
    return _find_by_desc(xml, re.compile(r"(?i)^unlink$|unlink"))


def _find_no_linked_apps(xml: str) -> dict | None:
    return _find_by_desc(xml, re.compile(r"(?i)no\s*app.*linked|no\s*linked\s*app"))


def gopay_unlink_openai(
    serial: str = "emulator-5554",
    timeout: float = 60.0,
    log: Callable[[str], None] = print,
) -> dict:
    """ADB UI 自动化：取消 GoPay 对 OpenAI 的关联。

    Returns:
        {"ok": True/False, "message": str}
    """
    log(f"[unlink] 开始 GoPay unlink OpenAI (device={serial})")

    # Step 1: 强制停止再启动 GoPay，确保干净状态
    _shell(serial, "am", "force-stop", "com.gojek.gopay")
    time.sleep(1)
    _shell(serial, "am", "start", "-n", "com.gojek.gopay/.MainActivity")
    time.sleep(5)
    xml = _dump_ui(serial)

    # Step 2: 定位 Profile tab 并导航到 Account 页面
    # GoPay 启动后默认在 Home 页面，需要先切到 Profile tab
    profile_tab = _find_by_desc(xml, re.compile(r"(?i)^profile$"))
    if profile_tab:
        _tap_node(serial, profile_tab, log, "Profile tab")
        time.sleep(3)
        xml = _dump_ui(serial)
    else:
        log(f"[unlink] 当前页面元素: {_dump_all_descs(xml)[:15]}")

    # Step 3: 找到并点击 "Account & app settings"
    # content-desc 包含完整描述: "Account & app settings\nControl your app preferences..."
    settings_node = _find_by_desc(xml, re.compile(
        r"(?i)account\s*&?\s*app\s*setting"
    ))
    if not settings_node:
        # 可能在 Profile 页面下面，先滑动
        _shell(serial, "input", "swipe", "450", "1200", "450", "400", "300")
        time.sleep(2)
        xml = _dump_ui(serial)
        settings_node = _find_by_desc(xml, re.compile(
            r"(?i)account\s*&?\s*app\s*setting"
        ))

    if not settings_node:
        descs = _dump_all_descs(xml)
        log(f"[unlink] 未找到 Account & app settings，当前页面元素: {descs[:15]}")
        _back(serial)
        return {"ok": False, "message": f"未找到 Account & app settings 入口。页面元素: {descs[:10]}"}

    _tap_node(serial, settings_node, log, "Account & app settings")
    time.sleep(2)
    xml = _dump_ui(serial)

    # Step 4: 找到并点击 "Linked apps"
    linked_node = _find_by_desc(xml, re.compile(r"(?i)linked\s*app"))
    if not linked_node:
        _shell(serial, "input", "swipe", "450", "1000", "450", "400", "300")
        time.sleep(1)
        xml = _dump_ui(serial)
        linked_node = _find_by_desc(xml, re.compile(r"(?i)linked\s*app"))

    if not linked_node:
        log("[unlink] 未找到 Linked apps 入口")
        _back(serial)
        return {"ok": False, "message": "未找到 Linked apps 入口"}

    _tap_node(serial, linked_node, log, "Linked apps")

    # Step 5: 等待 Linked apps 页面加载完成（数据异步加载）
    openai_node = None
    load_deadline = time.time() + 15
    while time.time() < load_deadline:
        time.sleep(2)
        xml = _dump_ui(serial)
        openai_node = _find_by_desc(xml, re.compile(r"(?i)openai|open\s*ai|chatgpt"))
        if openai_node:
            break
        # 如果确认显示"无关联应用"则停止等待
        no_apps = _find_by_desc(xml, re.compile(r"(?i)no\s*app.*linked"))
        if no_apps:
            log("[unlink] 已关联应用列表为空（已解绑或从未关联）")
            _back(serial)
            return {"ok": True, "message": "已关联应用列表为空（已解绑或从未关联）"}

    if not openai_node:
        descs = _dump_all_descs(xml)
        log(f"[unlink] Linked apps 页面加载后未找到 OpenAI，元素: {descs[:10]}")
        _back(serial)
        return {"ok": True, "message": "已关联应用列表中未找到 OpenAI（已解绑或从未关联）"}

    attempts = 0
    last_descs: list[str] = []
    for attempt in range(1, 4):
        attempts = attempt
        log(f"[unlink] unlink 尝试 {attempt}/3")
        openai_node = _find_openai_linked(xml)
        if not openai_node:
            _back(serial)
            _back(serial)
            log("[unlink] GoPay OpenAI unlink 成功")
            return {"ok": True, "message": "GoPay 已成功取消 OpenAI 关联", "attempts": attempt - 1}

        # Step 6: 找到 OpenAI 条目旁的 Unlink 按钮。找不到时先点 OpenAI 条目进入详情页。
        unlink_btn = _find_unlink_button(xml)
        if not unlink_btn:
            _tap_node(serial, openai_node, log, "OpenAI 条目")
            time.sleep(2)
            xml = _dump_ui(serial)
            unlink_btn = _find_unlink_button(xml)

        if not unlink_btn:
            last_descs = _dump_all_descs(xml)
            log(f"[unlink] 未找到 Unlink 按钮，当前页面元素: {last_descs[:10]}")
            break

        _tap_node(serial, unlink_btn, log, "Unlink")
        time.sleep(2)

        # Step 7: 确认弹窗 — 查找确认 Unlink 按钮
        xml = _dump_ui(serial)
        confirm_dialog = _find_by_desc(xml, re.compile(r"(?i)unlink.*from.*gopay"))
        if confirm_dialog:
            confirm_btn = _find_unlink_button(xml)
            if confirm_btn:
                _tap_node(serial, confirm_btn, log, "确认 Unlink")
                time.sleep(5)
            else:
                last_descs = _dump_all_descs(xml)
                log(f"[unlink] 确认弹窗出现但未找到确认按钮，元素: {last_descs[:10]}")
                _back(serial)
                time.sleep(1)
        else:
            log("[unlink] 未出现确认弹窗，可能已直接解绑")
            time.sleep(3)

        # Step 8: 验证结果。GoPay 有时异步更新，短轮询再判定。
        verify_deadline = time.time() + 12
        while time.time() < verify_deadline:
            xml = _dump_ui(serial)
            if _find_no_linked_apps(xml) or not _find_openai_linked(xml):
                _back(serial)
                _back(serial)
                log("[unlink] GoPay OpenAI unlink 成功")
                return {"ok": True, "message": "GoPay 已成功取消 OpenAI 关联", "attempts": attempt}
            time.sleep(2)

        last_descs = _dump_all_descs(xml)
        log(f"[unlink] 第 {attempt}/3 次解绑后 OpenAI 仍在列表中，准备兜底重试")
        # 回到列表/刷新当前页面，避免卡在详情页或旧弹窗。
        _back(serial)
        time.sleep(1)
        xml = _dump_ui(serial)
        if not _find_openai_linked(xml):
            _back(serial)
            xml = _dump_ui(serial)

    log("[unlink] 解绑后 OpenAI 仍在列表中，可能未成功")
    _back(serial)
    _back(serial)
    return {
        "ok": False,
        "message": "执行了 Unlink 操作但 OpenAI 仍在列表中",
        "attempts": attempts,
        "debug_descs": last_descs[:10],
    }
