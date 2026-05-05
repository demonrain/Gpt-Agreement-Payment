"""Appium WhatsApp UI 自动化 OTP Provider。

通过 Appium 控制 Android 设备/模拟器上的 WhatsApp App，
自动打开最新 GoPay 对话并读取 OTP 消息。

前置条件:
  - Appium Server 已启动（默认 http://127.0.0.1:4723）
  - Android 设备/模拟器已连接 ADB
  - WhatsApp 已安装并登录
  - pip install Appium-Python-Client

配置示例:
  "gopay": {
    "otp": {
      "source": "appium",
      "appium_url": "http://127.0.0.1:4723",
      "adb_serial": "emulator-5554",
      "timeout": 300,
      "interval": 5
    }
  }
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

_DEFAULT_OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_GOPAY_KEYWORDS = re.compile(
    r"gopay|go-pay|verif|kode|code|otp|one.?time|sandi",
    re.IGNORECASE,
)


def _find_otp_in_messages(texts: list[str]) -> Optional[str]:
    """从消息文本列表中（最新在前）查找包含 GoPay 关键词的 OTP。"""
    for text in texts:
        if _GOPAY_KEYWORDS.search(text):
            m = _DEFAULT_OTP_RE.search(text)
            if m:
                return m.group(1)
    return None


def appium_otp_provider(
    appium_url: str = "http://127.0.0.1:4723",
    serial: str = "",
    timeout: float = 300.0,
    interval: float = 5.0,
    log: Callable[[str], None] = print,
) -> Callable[[], str]:
    """工厂函数: 返回一个阻塞式 Callable，通过 Appium 从 WhatsApp 读取 GoPay OTP。"""

    def provider() -> str:
        try:
            from appium import webdriver
            from appium.options.android import UiAutomator2Options
            from appium.webdriver.common.appiumby import AppiumBy
        except ImportError:
            raise RuntimeError(
                "Appium OTP Provider 需要安装依赖: pip install Appium-Python-Client"
            )

        log(f"[gopay] waiting WhatsApp OTP via Appium: {appium_url}")

        caps = UiAutomator2Options()
        caps.platform_name = "Android"
        caps.app_package = "com.whatsapp"
        caps.app_activity = "com.whatsapp.Main"
        caps.no_reset = True
        caps.auto_grant_permissions = True
        if serial:
            caps.udid = serial

        driver = None
        try:
            driver = webdriver.Remote(appium_url, options=caps)
            driver.implicitly_wait(10)

            deadline = time.time() + timeout

            while time.time() < deadline:
                try:
                    # 尝试在聊天列表页查找最新消息片段
                    otp = _try_extract_from_chat_list(driver)
                    if otp:
                        log(f"[gopay] Appium: OTP={otp} (from chat list)")
                        return otp

                    # 尝试打开 GoPay 相关对话并读取详细消息
                    otp = _try_extract_from_conversation(driver)
                    if otp:
                        log(f"[gopay] Appium: OTP={otp} (from conversation)")
                        return otp

                except Exception as e:
                    log(f"[gopay] Appium: poll error: {e}")

                time.sleep(interval)

            raise TimeoutError(
                f"Appium WhatsApp OTP timeout after {timeout}s"
            )
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _try_extract_from_chat_list(driver) -> Optional[str]:
        """在 WhatsApp 聊天列表页面提取最新消息预览中的 OTP。"""
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            # WhatsApp 聊天列表中每条对话有消息预览 snippet
            snippets = driver.find_elements(
                AppiumBy.ID, "com.whatsapp:id/conversations_row_message_span"
            )
            texts = [s.text for s in snippets if s.text]
            return _find_otp_in_messages(texts)
        except Exception:
            return None

    def _try_extract_from_conversation(driver) -> Optional[str]:
        """尝试点击 GoPay 相关对话并从消息中提取 OTP。"""
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            # 查找包含 GoPay/gopay 关键词的对话
            contacts = driver.find_elements(
                AppiumBy.ID, "com.whatsapp:id/conversations_row_contact_name"
            )
            target = None
            for c in contacts:
                name = (c.text or "").lower()
                if "gopay" in name or "go-pay" in name:
                    target = c
                    break

            if not target:
                return None

            target.click()
            time.sleep(2)

            # 读取消息列表（从最新到最旧）
            messages = driver.find_elements(
                AppiumBy.ID, "com.whatsapp:id/message_text"
            )
            texts = [m.text for m in reversed(messages) if m.text]
            otp = _find_otp_in_messages(texts)

            # 返回聊天列表
            try:
                driver.back()
                time.sleep(1)
            except Exception:
                pass

            return otp
        except Exception:
            return None

    return provider
