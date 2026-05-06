import httpx
from pydantic import BaseModel
from ._common import CheckResult, PreflightResult, aggregate, resolve_system_proxy

WS_API = "https://proxy.webshare.io/api/v2"


class WebshareInput(BaseModel):
    api_key: str


def _build_result(checks: list[CheckResult]) -> PreflightResult:
    """aggregate + 把首条 check 的 message 写入顶层，方便 UI 直接显示"""
    result = aggregate(checks)
    if checks:
        result.message = checks[0].message
    return result


def check(body: dict) -> PreflightResult:
    cfg = WebshareInput.model_validate(body)
    headers = {"Authorization": f"Token {cfg.api_key}"}
    proxy = resolve_system_proxy()
    try:
        with httpx.Client(timeout=15.0, proxy=proxy) as c:
            r = c.get(f"{WS_API}/proxy/list/", headers=headers,
                      params={"mode": "backbone", "page_size": 1})
            if r.status_code == 400:
                r = c.get(f"{WS_API}/proxy/list/", headers=headers,
                          params={"mode": "direct", "page_size": 1})
    except Exception as e:
        tag = f"proxy={proxy}" if proxy else "direct"
        return _build_result([CheckResult(
            name="api", status="fail",
            message=f"[{tag}] {type(e).__name__}: {e}")])
    if r.status_code == 200:
        data = r.json()
        return _build_result([CheckResult(
            name="api", status="ok",
            message=f"{data.get('count', '?')} proxies available")])
    return _build_result([CheckResult(
        name="api", status="fail",
        message=f"HTTP {r.status_code}: {r.text[:200]}")])
