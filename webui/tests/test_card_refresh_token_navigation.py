import importlib.util
import sys
import types
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
        self._ready_selectors = set()
        self._browser_error_ids = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        outcome = self._outcomes.pop(0)
        self.url = outcome.get("url", self.url)
        self._ready_selectors = set(outcome.get("ready_selectors", []))
        self._browser_error_ids = list(outcome.get("browser_error_ids", []))
        error = outcome.get("error")
        if error:
            raise RuntimeError(error)
        return None

    def wait_for_load_state(self, state=None, timeout=None):
        self.load_state_calls += 1
        return None

    def query_selector(self, selector):
        return object() if selector in self._ready_selectors else None

    def evaluate(self, _script):
        return {
            "documentURI": "about:neterror?e=netReset&u=https://auth.openai.com/oauth/authorize"
            if self._browser_error_ids
            else self.url,
            "title": "Problem loading page" if self._browser_error_ids else "",
            "buttonIds": self._browser_error_ids,
            "bodyText": "The connection was reset. Try Again" if self._browser_error_ids else "",
        }


class FakeConsentButton:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def is_visible(self):
        return True

    def click(self):
        self.page.clicked_selectors.append(self.selector)
        self.page.trigger_callback("http://localhost:1455/auth/callback?code=auth-code")


class FakeVisibleNode:
    def __init__(self):
        self.clicks = 0

    def is_visible(self):
        return True

    def click(self):
        self.clicks += 1


class FakeSelectorPage:
    def __init__(self, visible_selectors):
        self.visible_selectors = set(visible_selectors)
        self.node = FakeVisibleNode()

    def query_selector(self, selector):
        return self.node if selector in self.visible_selectors else None


class FakeRouteRequest:
    def __init__(self, url):
        self.url = url


class FakeRoute:
    def __init__(self, url):
        self.request = FakeRouteRequest(url)
        self.fulfilled = False

    def fulfill(self, **_kwargs):
        self.fulfilled = True

    def abort(self):
        pass


class FakeRefreshTokenPage:
    def __init__(self):
        self.url = "about:blank"
        self.routes = {}
        self.wait_for_selector_calls = []
        self.clicked_selectors = []

    def route(self, pattern, handler):
        self.routes[pattern] = handler

    def unroute(self, pattern):
        self.routes.pop(pattern, None)

    def goto(self, url, wait_until=None, timeout=None):
        self.url = url
        return None

    def wait_for_load_state(self, state=None, timeout=None):
        return None

    def wait_for_selector(self, selector, state=None, timeout=None):
        self.wait_for_selector_calls.append(
            {"selector": selector, "state": state, "timeout": timeout}
        )
        raise TimeoutError(f"no selector: {selector}")

    def query_selector(self, selector):
        if selector == 'button:has-text("Authorize")':
            return FakeConsentButton(self, selector)
        if selector == 'button[type="submit"]':
            return FakeConsentButton(self, selector)
        return None

    def query_selector_all(self, selector):
        return []

    def evaluate(self, _script):
        return [{"text": "Authorize", "type": "submit", "tag": "BUTTON"}]

    def screenshot(self, **_kwargs):
        return None

    def trigger_callback(self, url):
        self.url = url
        handler = self.routes.get("http://localhost:1455/**")
        if handler:
            handler(FakeRoute(url))


class FakeRefreshTokenContext:
    def __init__(self, page):
        self.pages = [page]

    def new_page(self):
        return self.pages[0]


class FakeCamoufox:
    page = None
    last_kwargs = None

    def __init__(self, **_kwargs):
        type(self).last_kwargs = _kwargs
        self.context = FakeRefreshTokenContext(self.page)

    def __enter__(self):
        return self.context

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeScreen:
    def __init__(self, **_kwargs):
        pass


class FakeTokenResponse:
    status_code = 200
    text = '{"refresh_token":"rt_test"}'

    def json(self):
        return {"refresh_token": "rt_test"}


class FakeCffiSession:
    def __init__(self, **_kwargs):
        self.posts = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return FakeTokenResponse()


def _install_refresh_token_fakes(monkeypatch, page):
    FakeCamoufox.page = page
    FakeCamoufox.last_kwargs = None
    monkeypatch.setitem(
        __import__("sys").modules,
        "camoufox",
        types.ModuleType("camoufox"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "camoufox.sync_api",
        types.SimpleNamespace(Camoufox=FakeCamoufox),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "browserforge",
        types.ModuleType("browserforge"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "browserforge.fingerprints",
        types.SimpleNamespace(Screen=FakeScreen),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "curl_cffi",
        types.ModuleType("curl_cffi"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "curl_cffi.requests",
        types.SimpleNamespace(Session=FakeCffiSession),
    )


def test_rt_open_authorize_page_retries_after_net_reset_blank_url():
    card = _load_card_module()
    logs = []
    page = FakeAuthorizePage([
        {"url": "about:blank", "error": "Page.goto: NS_ERROR_NET_RESET"},
        {
            "url": "https://auth.openai.com/log-in",
            "ready_selectors": ['input[type="email"]'],
        },
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
        {
            "url": "https://auth.openai.com/log-in",
            "error": "Page.goto: NS_ERROR_NET_RESET",
            "ready_selectors": ['input[type="email"]'],
        },
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


def test_rt_open_authorize_page_retries_when_url_changed_but_dom_not_ready():
    card = _load_card_module()
    logs = []
    page = FakeAuthorizePage([
        {
            "url": "https://auth.openai.com/oauth/authorize?client_id=app_test",
            "error": "Page.goto: NS_ERROR_NET_RESET",
        },
        {
            "url": "https://auth.openai.com/log-in",
            "ready_selectors": ['input[type="email"]'],
        },
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
    assert any("页面未就绪" in line for line in logs)


def test_rt_open_authorize_page_retries_firefox_neterror_page_with_authorize_url():
    card = _load_card_module()
    logs = []
    page = FakeAuthorizePage([
        {
            "url": "https://auth.openai.com/oauth/authorize?client_id=app_test",
            "error": "Page.goto: NS_ERROR_NET_RESET",
            "ready_selectors": ['button:has-text("Continue")'],
            "browser_error_ids": ["neterrorTryAgainButton"],
        },
        {
            "url": "https://auth.openai.com/log-in",
            "ready_selectors": ['input[type="email"]'],
        },
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
    assert any("网络错误页" in line for line in logs)


def test_rt_email_selectors_accept_username_login_input():
    card = _load_card_module()
    page = FakeSelectorPage(['input[name="username"]:visible'])

    node = card._rt_first_visible(page, card._RT_EMAIL_SELECTORS)

    assert node is page.node


def test_resolve_refresh_token_proxy_uses_fresh_checkout_proxy_override():
    card = _load_card_module()
    cfg = {
        "proxy": "socks5h://127.0.0.1:18898",
        "fresh_checkout": {"proxy": "http://fresh-proxy.local:8080"},
    }

    proxy_url = card._resolve_refresh_token_proxy_url(cfg)

    assert proxy_url == "http://fresh-proxy.local:8080"


def test_resolve_refresh_token_proxy_uses_stage_proxy_override_first():
    card = _load_card_module()
    cfg = {
        "proxy": "socks5h://127.0.0.1:18898",
        "fresh_checkout": {"proxy": "http://fresh-proxy.local:8080"},
        "stage_proxies": {"refresh_token": "http://rt-proxy.local:8080"},
    }

    proxy_url = card._resolve_refresh_token_proxy_url(cfg)

    assert proxy_url == "http://rt-proxy.local:8080"


def test_build_camoufox_proxy_uses_local_socks_relay_for_authenticated_socks(monkeypatch):
    card = _load_card_module()
    calls = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_create_connection(target, timeout=None):
        calls.append({"target": target, "timeout": timeout})
        return FakeSocket()

    monkeypatch.setattr("socket.create_connection", fake_create_connection)

    proxy = card._build_camoufox_proxy("socks5://user:secret@example.invalid:1080")

    assert proxy == {"server": "socks5://127.0.0.1:18898"}
    assert calls == [{"target": ("127.0.0.1", 18898), "timeout": 2}]


def test_fetch_openai_login_otp_passes_original_issue_time(monkeypatch):
    card = _load_card_module()
    calls = []

    class FakeProvider:
        @classmethod
        def from_env_or_secrets(cls):
            return cls()

        def wait_for_otp(self, email_addr, timeout=None, issued_after=None):
            calls.append(
                {
                    "email": email_addr,
                    "timeout": timeout,
                    "issued_after": issued_after,
                }
            )
            return "123456"

    monkeypatch.setitem(
        sys.modules,
        "cf_kv_otp_provider",
        types.SimpleNamespace(CloudflareKVOtpProvider=FakeProvider),
    )

    otp = card._fetch_openai_login_otp(
        "buyer@example.com",
        timeout=30,
        issued_after=1234.5,
    )

    assert otp == "123456"
    assert calls == [
        {"email": "buyer@example.com", "timeout": 30, "issued_after": 1234.5}
    ]


def test_fetch_openai_login_otp_accepts_code_arrived_before_wait_started(monkeypatch):
    card = _load_card_module()
    wait_started = 1020.0

    class FakeProvider:
        @classmethod
        def from_env_or_secrets(cls):
            return cls()

        def wait_for_otp(self, email_addr, timeout=None, issued_after=None):
            if issued_after is None or issued_after >= wait_started:
                raise TimeoutError("old code ignored")
            return "654321"

    monkeypatch.setitem(
        sys.modules,
        "cf_kv_otp_provider",
        types.SimpleNamespace(CloudflareKVOtpProvider=FakeProvider),
    )

    otp = card._fetch_openai_login_otp(
        "buyer@example.com",
        timeout=30,
        issued_after=1000.0,
    )

    assert otp == "654321"


def test_rt_click_otp_resend_clicks_visible_resend_button():
    card = _load_card_module()
    button = FakeVisibleNode()

    class FakePage:
        def query_selector(self, selector):
            if selector == 'button:has-text("Resend")':
                return button
            return None

    clicked = card._rt_click_otp_resend(FakePage())

    assert clicked is True
    assert button.clicks == 1


def test_exchange_refresh_token_normalizes_socks5h_proxy_for_camoufox(monkeypatch):
    card = _load_card_module()
    page = FakeRefreshTokenPage()
    _install_refresh_token_fakes(monkeypatch, page)
    monkeypatch.setattr(card.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(card.random, "uniform", lambda _start, _end: 0)
    monkeypatch.setattr(card, "_log", lambda _line: None)

    token = card._exchange_refresh_token_with_session(
        email="buyer@example.com",
        password="unused-password",
        mail_cfg={"provider": "unused"},
        proxy_url="socks5h://127.0.0.1:18898",
    )

    assert token == "rt_test"
    assert FakeCamoufox.last_kwargs["proxy"] == {"server": "socks5://127.0.0.1:18898"}


def test_exchange_refresh_token_fails_when_configured_proxy_is_unusable(monkeypatch):
    card = _load_card_module()
    page = FakeRefreshTokenPage()
    _install_refresh_token_fakes(monkeypatch, page)
    monkeypatch.setattr(card.time, "sleep", lambda _seconds: None)
    logs = []
    monkeypatch.setattr(card, "_log", logs.append)
    monkeypatch.setattr(card, "_build_camoufox_proxy", lambda _proxy_url: None)

    token = card._exchange_refresh_token_with_session(
        email="buyer@example.com",
        password="unused-password",
        mail_cfg={"provider": "unused"},
        proxy_url="socks5://user:secret@example.invalid:1080",
    )

    assert token == ""
    assert FakeCamoufox.last_kwargs is None
    assert any("代理已配置但 Camoufox 不可用" in line for line in logs)
    assert all("secret" not in line for line in logs)


def test_exchange_refresh_token_continues_when_authorize_page_has_no_email_input(monkeypatch):
    card = _load_card_module()
    page = FakeRefreshTokenPage()
    _install_refresh_token_fakes(monkeypatch, page)
    monkeypatch.setattr(card.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(card.random, "uniform", lambda _start, _end: 0)
    logs = []
    monkeypatch.setattr(card, "_log", logs.append)

    token = card._exchange_refresh_token_with_session(
        email="buyer@example.com",
        password="unused-password",
        mail_cfg={"provider": "unused"},
    )

    assert token == "rt_test"
    assert page.wait_for_selector_calls == []
    assert page.clicked_selectors == ['button:has-text("Authorize")']
    assert any("跳过邮箱填写" in line for line in logs)
