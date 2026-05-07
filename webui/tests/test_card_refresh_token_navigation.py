import importlib.util
from pathlib import Path


def _load_card_module():
    repo_root = Path(__file__).resolve().parents[2]
    card_path = repo_root / "CTF-pay" / "card.py"
    spec = importlib.util.spec_from_file_location("ctf_pay_card_for_test", card_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeAuthorizePage:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.url = "about:blank"
        self.goto_calls = []
        self.load_state_calls = 0

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        outcome = self._outcomes.pop(0)
        self.url = outcome.get("url", self.url)
        error = outcome.get("error")
        if error:
            raise RuntimeError(error)
        return None

    def wait_for_load_state(self, state=None, timeout=None):
        self.load_state_calls += 1
        return None


def test_rt_open_authorize_page_retries_after_net_reset_blank_url():
    card = _load_card_module()
    logs = []
    page = FakeAuthorizePage([
        {"url": "about:blank", "error": "Page.goto: NS_ERROR_NET_RESET"},
        {"url": "https://auth.openai.com/log-in"},
    ])

    ok = card._rt_open_authorize_page(
        page,
        "https://auth.openai.com/oauth/authorize?client_id=app_test",
        attempts=3,
        log_func=logs.append,
        sleep_func=lambda _seconds: None,
    )

    assert ok is True
    assert len(page.goto_calls) == 2
    assert any("goto 异常(1/3)" in line for line in logs)


def test_rt_open_authorize_page_fails_when_all_attempts_stay_blank():
    card = _load_card_module()
    logs = []
    page = FakeAuthorizePage([
        {"url": "about:blank", "error": "Page.goto: NS_ERROR_NET_RESET"},
        {"url": "about:blank", "error": "Page.goto: NS_ERROR_NET_RESET"},
        {"url": "about:blank", "error": "Page.goto: Timeout 30000ms exceeded"},
    ])

    ok = card._rt_open_authorize_page(
        page,
        "https://auth.openai.com/oauth/authorize?client_id=app_test",
        attempts=3,
        log_func=logs.append,
        sleep_func=lambda _seconds: None,
    )

    assert ok is False
    assert len(page.goto_calls) == 3
    assert any("authorize URL 打开失败" in line for line in logs)


def test_rt_open_authorize_page_accepts_loaded_page_after_goto_exception():
    card = _load_card_module()
    page = FakeAuthorizePage([
        {"url": "https://auth.openai.com/log-in", "error": "Page.goto: NS_ERROR_NET_RESET"},
    ])

    ok = card._rt_open_authorize_page(
        page,
        "https://auth.openai.com/oauth/authorize?client_id=app_test",
        attempts=3,
        log_func=lambda _line: None,
        sleep_func=lambda _seconds: None,
    )

    assert ok is True
    assert len(page.goto_calls) == 1
