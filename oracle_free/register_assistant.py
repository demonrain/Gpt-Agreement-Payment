from __future__ import annotations

from dataclasses import dataclass

from .config import OracleFreeConfig


FREE_URL = "https://www.oracle.com/cloud/free/"


@dataclass
class AssistantStep:
    name: str
    action: str
    manual: bool = False


def planned_steps(cfg: OracleFreeConfig) -> list[AssistantStep]:
    profile = cfg.profile
    return [
        AssistantStep("open", f"Open {FREE_URL}"),
        AssistantStep("start", "Click the free trial / start for free call to action"),
        AssistantStep(
            "profile",
            (
                "Prefill owner profile fields where Oracle exposes stable labels: "
                f"{profile.first_name} {profile.last_name}, {profile.email}, "
                f"country={profile.country}, home_region={profile.home_region}"
            ),
        ),
        AssistantStep(
            "verification",
            "Pause for the owner to complete CAPTCHA, phone verification, email verification, payment verification, and terms acceptance",
            manual=True,
        ),
        AssistantStep(
            "console",
            "After the owner reaches OCI Console, stop and print next steps for OCI CLI / Terraform",
            manual=True,
        ),
    ]


def print_dry_run(cfg: OracleFreeConfig) -> None:
    print("Oracle Free Tier registration assistant plan")
    print(f"URL: {FREE_URL}")
    print()
    for idx, step in enumerate(planned_steps(cfg), start=1):
        marker = "manual" if step.manual else "auto"
        print(f"{idx}. [{marker}] {step.action}")
    print()
    print("Safety boundary: CAPTCHA, phone OTP, email OTP, card verification, and terms acceptance stay manual.")


def run_browser_assistant(cfg: OracleFreeConfig) -> int:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for browser mode. Install it or run with --dry-run."
        ) from exc

    browser_cfg = cfg.browser
    profile = cfg.profile
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=browser_cfg.headless,
            slow_mo=browser_cfg.slow_mo_ms,
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto(FREE_URL, wait_until="domcontentloaded", timeout=browser_cfg.timeout_ms)
        _click_start_button(page, browser_cfg.timeout_ms)
        _fill_if_present(page, ["input[name='email']", "input[type='email']"], profile.email)
        _fill_by_label(page, "First name", profile.first_name)
        _fill_by_label(page, "Last name", profile.last_name)
        _fill_by_label(page, "Cloud account name", profile.cloud_account_name)
        _fill_by_label(page, "Home region", profile.home_region)
        print("Browser assistant is paused for manual Oracle verification.")
        print("Complete CAPTCHA, phone/email OTP, payment verification, and terms acceptance in the opened browser.")
        print("Press Enter here after you reach the OCI Console, or Ctrl+C to stop.")
        try:
            input()
        finally:
            context.close()
            browser.close()
    return 0


def _click_start_button(page, timeout_ms: int) -> None:
    candidates = [
        "a:has-text('Start for free')",
        "a:has-text('Try Oracle Cloud Free Tier')",
        "a:has-text('Free Trial')",
        "text=Start for free",
    ]
    for selector in candidates:
        try:
            page.locator(selector).first.click(timeout=8000)
            return
        except Exception:
            continue
    print("Could not find a stable start button; leaving the Oracle Free page open for manual navigation.")


def _fill_if_present(page, selectors: list[str], value: str) -> None:
    if not value:
        return
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.fill(value, timeout=3000)
            return
        except Exception:
            continue


def _fill_by_label(page, label: str, value: str) -> None:
    if not value:
        return
    try:
        page.get_by_label(label, exact=False).fill(value, timeout=3000)
    except Exception:
        return
