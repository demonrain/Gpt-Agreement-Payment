import httpx
from pydantic import BaseModel
from ._common import CheckResult, PreflightResult, aggregate


class Sub2apiInput(BaseModel):
    base_url: str
    token: str


def check(body: dict) -> PreflightResult:
    cfg = Sub2apiInput.model_validate(body)
    base = cfg.base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {cfg.token}",
        "x-api-key": cfg.token,
        "Content-Type": "application/json",
    }
    url = f"{base}/admin/accounts"
    url_alt = f"{base}/api/v1/admin/accounts" if "/api/" not in base else None
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as c:
            r = c.get(url, headers=headers, params={"page": 1, "size": 1})
            if "text/html" in r.headers.get("content-type", "") and url_alt:
                r = c.get(url_alt, headers=headers, params={"page": 1, "size": 1})
    except httpx.HTTPError as e:
        return aggregate([CheckResult(name="sub2api", status="fail",
                                      message=f"连接失败: {e}")])
    if r.status_code == 200:
        try:
            data = r.json()
            total = data.get("total", "?") if isinstance(data, dict) else "?"
        except Exception:
            total = "?"
        return aggregate([CheckResult(name="sub2api", status="ok",
                                      message=f"sub2api 可达（当前 {total} 个账号）")])
    if r.status_code in (401, 403):
        return aggregate([CheckResult(name="sub2api", status="fail",
                                      message=f"HTTP {r.status_code} — token 无效或权限不足",
                                      details=r.text[:500])])
    return aggregate([CheckResult(name="sub2api", status="fail",
                                  message=f"HTTP {r.status_code}",
                                  details=r.text[:1000])])
