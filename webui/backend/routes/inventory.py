"""Local account inventory: list, validate, delete, push to CPA, retry payment."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..account_inventory import build_accounts_inventory
from ..account_validator import validate_accounts
from ..db import get_db
from .. import settings as s
from .. import runner
from .. import sub2api_push


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


class IdsRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)


class RetryPayRequest(BaseModel):
    id: int


class CheckRequest(IdsRequest):
    timeout_s: float = 10.0
    max_workers: int = 3


def _load_cpa_cfg() -> dict:
    try:
        cfg = json.loads(s.PAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读 PAY_CONFIG_PATH 失败: {e}")
    cpa = (cfg.get("cpa") or {})
    if not cpa.get("enabled"):
        raise HTTPException(status_code=400,
                            detail="CPA 未启用：请先在 wizard Step11 填 base_url + admin_key 并启用")
    if not (cpa.get("base_url") and cpa.get("admin_key")):
        raise HTTPException(status_code=400, detail="CPA 配置缺 base_url 或 admin_key")
    return cpa


def _do_cpa_push(account: dict, cpa_cfg: dict) -> dict:
    """Run the CPA push for one account using pipeline._cpa_import_after_team.
    Records outcome to pipeline_results so inventory reflects new state."""
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import pipeline  # type: ignore

    email = account.get("email", "")
    rt = (account.get("refresh_token") or "").strip()
    is_free = False  # caller will set via plan_tag if needed; default False == use plan_tag
    try:
        status = pipeline._cpa_import_after_team(
            email, "", cpa_cfg, refresh_token=rt, is_free=is_free,
        )
    except Exception as e:
        status = f"error: {type(e).__name__}: {str(e)[:120]}"

    # 记一条 pipeline_results 让 inventory 的 cpa_status 能反映本次推送
    try:
        get_db().add_pipeline_result({
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "cpa_push_manual",
            "status": "ok" if status == "ok" else "fail",
            "registration": {"status": "reused", "email": email},
            "payment": {"status": "skipped", "email": email},
            "cpa_import": status,
        })
    except Exception:
        pass
    return {"id": account.get("id"), "email": email, "status": status}


@router.get("/accounts")
def get_accounts(user: str = CurrentUser):
    return build_accounts_inventory()


@router.post("/accounts/check")
def check_accounts(req: CheckRequest, user: str = CurrentUser):
    """Probe each account's session via OpenAI's /api/auth/session.
    Body: {ids: [account_id, ...], timeout_s?, max_workers?}.
    Returns per-account {id, email, status, message} (status: valid|invalid|unknown)."""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    if len(req.ids) > 500:
        raise HTTPException(status_code=400, detail="单次最多 500 个")
    workers = max(1, min(int(req.max_workers), 8))
    timeout = max(2.0, min(float(req.timeout_s), 30.0))
    results = validate_accounts(req.ids, max_workers=workers, timeout_s=timeout)
    summary = {
        "total": len(results),
        "valid": sum(1 for r in results if r.get("status") == "valid"),
        "invalid": sum(1 for r in results if r.get("status") == "invalid"),
        "unknown": sum(1 for r in results if r.get("status") == "unknown"),
    }
    return {"results": results, "summary": summary}


@router.post("/accounts/delete")
def delete_accounts(req: IdsRequest, user: str = CurrentUser):
    """Hard-delete accounts by id. Associated pipeline_results / card_results /
    oauth_status rows are kept (audit trail; lookup by email still works)."""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    n = get_db().delete_registered_accounts(req.ids)
    return {"deleted": n, "requested": len(req.ids)}


@router.post("/accounts/cpa-push")
def cpa_push(req: IdsRequest, user: str = CurrentUser):
    """Push selected accounts to CPA (CLIProxyAPI). Reuses
    pipeline._cpa_import_after_team. Each row's stored refresh_token (or
    fallback access_token) is used; records outcome to pipeline_results."""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    if len(req.ids) > 100:
        raise HTTPException(status_code=400, detail="单次最多 100 个")
    cpa_cfg = _load_cpa_cfg()
    db = get_db()
    results: list[dict] = []
    for aid in req.ids:
        acc = db.get_registered_account(int(aid))
        if not acc:
            results.append({"id": aid, "email": "", "status": "missing"})
            continue
        results.append(_do_cpa_push(acc, cpa_cfg))
    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r.get("status") == "ok"),
        "no_rt": sum(1 for r in results if r.get("status") == "no_rt"),
        "fail": sum(1 for r in results if r.get("status") not in ("ok", "no_rt", "skipped", "missing")),
    }
    return {"results": results, "summary": summary}


def _load_sub2api_cfg() -> dict:
    try:
        cfg = json.loads(s.PAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读 PAY_CONFIG_PATH 失败: {e}")
    sa = cfg.get("sub2api") or {}
    if not sa.get("enabled"):
        raise HTTPException(status_code=400,
                            detail="sub2api 未启用：请先在 wizard Step11 填 base_url + token 并启用")
    if not (sa.get("base_url") and sa.get("token")):
        raise HTTPException(status_code=400, detail="sub2api 配置缺 base_url 或 token")
    return sa


def _do_sub2api_push(accounts: list[dict], sub2api_cfg: dict) -> dict:
    """批量推送账号到 sub2api，记录结果到 pipeline_results。"""
    result = sub2api_push.push_to_sub2api(accounts, sub2api_cfg)
    status_str = "ok" if result.get("ok") else f"error: {result.get('error', 'unknown')}"
    for acc in accounts:
        email = acc.get("email", "")
        try:
            get_db().add_pipeline_result({
                "ts": datetime.now(timezone.utc).isoformat(),
                "mode": "sub2api_push_manual",
                "status": "ok" if result.get("ok") else "fail",
                "registration": {"status": "reused", "email": email},
                "payment": {"status": "skipped", "email": email},
                "sub2api_import": status_str,
            })
        except Exception:
            pass
    return result


@router.post("/accounts/sub2api-push")
def sub2api_push_endpoint(req: IdsRequest, user: str = CurrentUser):
    """推送选中账号到 sub2api。"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    if len(req.ids) > 200:
        raise HTTPException(status_code=400, detail="单次最多 200 个")
    sa_cfg = _load_sub2api_cfg()
    db = get_db()
    accounts = []
    missing = []
    for aid in req.ids:
        acc = db.get_registered_account(int(aid))
        if not acc:
            missing.append(aid)
            continue
        accounts.append(acc)
    result = _do_sub2api_push(accounts, sa_cfg)
    result["missing"] = len(missing)
    return result


@router.post("/accounts/retry-pay")
def retry_pay(req: RetryPayRequest, user: str = CurrentUser):
    """为指定已注册账号重新触发 pay-only 支付流程。
    前端「继续开通」按钮调用此接口。"""
    db = get_db()
    acc = db.get_registered_account(req.id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    email = (acc.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="账号缺少邮箱")
    has_session = bool(acc.get("session_token") or acc.get("access_token"))
    if not has_session:
        raise HTTPException(status_code=400, detail="账号缺少 session 凭证，无法继续开通")

    try:
        cfg = json.loads(s.PAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取支付配置失败: {e}")
    # GoPay 检测: 配置中有 gopay 块且包含手机号+PIN
    gp = cfg.get("gopay") or {}
    use_gopay = bool(gp.get("phone_number") and gp.get("pin"))
    use_paypal = not use_gopay

    try:
        result = runner.start(
            mode="single",
            paypal=use_paypal,
            pay_only=True,
            gopay=use_gopay,
            pay_only_email=email,
        )
        return {"status": "started", "email": email, "runner": result}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


class UnlinkRequest(BaseModel):
    adb_serial: str = "emulator-5554"


@router.post("/gopay-unlink")
def gopay_unlink(req: UnlinkRequest, user: str = CurrentUser):
    """手动触发 ADB UI 自动化 Unlink GoPay → OpenAI。"""
    import subprocess
    import sys
    from pathlib import Path

    ctf_pay_dir = s.ROOT / "CTF-pay"
    script = ctf_pay_dir / "gopay_unlink_adb.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail="gopay_unlink_adb.py 不存在")

    # 直接 import 执行（与 pipeline 同进程，ADB 命令是 subprocess.run）
    if str(ctf_pay_dir) not in sys.path:
        sys.path.insert(0, str(ctf_pay_dir))
    try:
        from gopay_unlink_adb import gopay_unlink_openai
        result = gopay_unlink_openai(serial=req.adb_serial)
        return result
    except Exception as e:
        return {"ok": False, "message": f"unlink 异常: {type(e).__name__}: {str(e)[:300]}"}
