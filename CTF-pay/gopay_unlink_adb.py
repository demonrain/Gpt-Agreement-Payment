"""ADB UI 自动化：从 GoPay 取消 OpenAI 关联。

支付成功后，GoPay 会保留 OpenAI 的"已关联应用"记录。
如果不取消关联，下次 linking 可能出现 406 "account already linked"。

本模块通过 ADB 操控 GoPay 应用 UI 来完成自动 Unlink。

流程:
  1. 启动 GoPay 应用
  2. 导航到 "探索" → "已关联应用" 或 "设置" → "已关联应用"
  3. 找到 OpenAI 条目
  4. 点击取消关联
  5. 确认取消
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
    """在 UI XML 中查找匹配属性的第一个节点，返回 bounds 中心坐标。"""
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


def _find_all_nodes(xml_str: str, **attrs) -> list[dict]:
    """查找所有匹配节点。"""
    results = []
    if not xml_str:
        return results
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return results
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
                results.append({
                    "x": (x1 + x2) // 2,
                    "y": (y1 + y2) // 2,
                    "text": elem.get("text", ""),
                    "content-desc": elem.get("content-desc", ""),
                    "resource-id": elem.get("resource-id", ""),
                })
    return results


def _wait_for_node(serial: str, timeout: float, interval: float, log: Callable, label: str, **attrs) -> dict | None:
    """等待 UI 节点出现。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        xml = _dump_ui(serial)
        node = _find_node(xml, **attrs)
        if node:
            return node
        time.sleep(interval)
    log(f"[unlink] 等待 {label} 超时 ({timeout}s)")
    return None


def gopay_unlink_openai(
    serial: str = "emulator-5554",
    timeout: float = 60.0,
    log: Callable[[str], None] = print,
) -> dict:
    """ADB UI 自动化：取消 GoPay 对 OpenAI 的关联。

    Returns:
        {"ok": True/False, "message": str}
    """
    interval = 2.0

    log(f"[unlink] 开始 GoPay unlink OpenAI (device={serial})")

    # Step 1: 启动 GoPay 应用
    _shell(serial, "am", "start", "-n",
           "com.gojek.gopay/com.gojek.gopay.activity.MainActivity")
    time.sleep(3)

    # Step 2: 尝试找到并进入已关联应用页面
    # GoPay 的 UI 可能有多种路径，尝试搜索"设置"或齿轮图标
    xml = _dump_ui(serial)

    # 方法A: 通过底部导航的"我的"/"Profil"/"Profile" tab
    profile_tab = (
        _find_node(xml, text=re.compile(r"(?i)profil|profile|我的|akun|saya"))
        or _find_node(xml, **{"content-desc": re.compile(r"(?i)profil|profile|我的|akun")})
    )
    if profile_tab:
        log(f"[unlink] 找到 Profile tab: ({profile_tab['x']}, {profile_tab['y']})")
        _tap(serial, profile_tab["x"], profile_tab["y"])
        time.sleep(2)
        xml = _dump_ui(serial)

    # 查找"设置"/"Settings"/"Pengaturan"
    settings_node = (
        _find_node(xml, text=re.compile(r"(?i)setting|设置|pengaturan|setelan"))
        or _find_node(xml, **{"content-desc": re.compile(r"(?i)setting|设置|pengaturan")})
    )
    if settings_node:
        log(f"[unlink] 找到 Settings: ({settings_node['x']}, {settings_node['y']})")
        _tap(serial, settings_node["x"], settings_node["y"])
        time.sleep(2)
        xml = _dump_ui(serial)

    # 查找"已关联应用"/"Linked Apps"/"Aplikasi Terhubung"
    linked_node = _find_node(xml, text=re.compile(
        r"(?i)linked\s*app|已关联|terhubung|tertaut|connected\s*app"
    ))
    if not linked_node:
        # 尝试向下滑动后再找
        _shell(serial, "input", "swipe", "300", "800", "300", "400", "300")
        time.sleep(1)
        xml = _dump_ui(serial)
        linked_node = _find_node(xml, text=re.compile(
            r"(?i)linked\s*app|已关联|terhubung|tertaut|connected\s*app"
        ))

    if not linked_node:
        log("[unlink] 未找到「已关联应用」入口")
        return {"ok": False, "message": "未找到「已关联应用」入口，GoPay UI 可能已变化"}

    log(f"[unlink] 找到 Linked Apps: ({linked_node['x']}, {linked_node['y']})")
    _tap(serial, linked_node["x"], linked_node["y"])
    time.sleep(2)

    # Step 3: 查找 OpenAI 条目
    xml = _dump_ui(serial)
    openai_node = _find_node(xml, text=re.compile(r"(?i)openai|open\s*ai|chatgpt"))
    if not openai_node:
        log("[unlink] 已关联应用列表中未找到 OpenAI 条目（可能已解绑）")
        return {"ok": True, "message": "已关联应用列表中未找到 OpenAI（已解绑或从未关联）"}

    log(f"[unlink] 找到 OpenAI 条目: ({openai_node['x']}, {openai_node['y']})")
    _tap(serial, openai_node["x"], openai_node["y"])
    time.sleep(2)

    # Step 4: 点击"取消关联"/"Unlink"/"Putuskan"
    xml = _dump_ui(serial)
    unlink_btn = _find_node(xml, text=re.compile(
        r"(?i)unlink|取消关联|解除关联|putuskan|hapus|disconnect|remove"
    ))
    if not unlink_btn:
        log("[unlink] 未找到 Unlink 按钮")
        return {"ok": False, "message": "进入了 OpenAI 详情页但未找到 Unlink 按钮"}

    log(f"[unlink] 点击 Unlink: ({unlink_btn['x']}, {unlink_btn['y']})")
    _tap(serial, unlink_btn["x"], unlink_btn["y"])
    time.sleep(2)

    # Step 5: 确认弹窗
    xml = _dump_ui(serial)
    confirm_btn = (
        _find_node(xml, text=re.compile(r"(?i)confirm|ya|yes|确认|确定|ok|lanjut"))
        or _find_node(xml, text=re.compile(r"(?i)unlink|putuskan"))
    )
    if confirm_btn:
        log(f"[unlink] 确认 Unlink: ({confirm_btn['x']}, {confirm_btn['y']})")
        _tap(serial, confirm_btn["x"], confirm_btn["y"])
        time.sleep(2)

    # Step 6: 验证是否成功
    xml = _dump_ui(serial)
    still_linked = _find_node(xml, text=re.compile(r"(?i)openai|open\s*ai|chatgpt"))
    if still_linked:
        log("[unlink] 解绑后 OpenAI 仍在列表中，可能未成功")
        return {"ok": False, "message": "执行了 Unlink 操作但 OpenAI 仍在列表中"}

    # 返回主界面
    _back(serial)
    time.sleep(1)
    _back(serial)

    log("[unlink] GoPay OpenAI unlink 成功")
    return {"ok": True, "message": "GoPay 已成功取消 OpenAI 关联"}
