"""sub2api 账号推送模块。

将 pipeline 产出的账号（access_token / refresh_token / account_id / email）
转换为 sub2api 导入格式并 POST 到 sub2api 管理接口。
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx


def _decode_jwt_payload(token: str) -> dict:
    """解析 JWT payload（不验签）。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        # 补齐 base64 padding
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}


def _parse_expired_time(expired_str: str) -> int:
    try:
        if not expired_str:
            return 0
        dt = datetime.fromisoformat(expired_str.replace("Z", "+00:00"))
        ts = int(dt.timestamp())
        return ts if ts > 0 else 0
    except Exception:
        return 0


def build_sub2api_account(account: dict, index: int) -> dict | None:
    """将单个 pipeline 账号转为 sub2api 导入格式。

    account 字典来自 registered_accounts 表或 pipeline_results，
    包含 email, access_token, refresh_token, account_id 等字段。
    """
    access_token = (account.get("access_token") or "").strip()
    refresh_token = (account.get("refresh_token") or "").strip()
    account_id = (account.get("account_id") or account.get("chatgpt_account_id") or "").strip()
    email = (account.get("email") or "").strip()

    if not access_token and not refresh_token:
        return None

    payload = _decode_jwt_payload(access_token) if access_token else {}
    auth_info = payload.get("https://api.openai.com/auth") or {}

    id_token = (account.get("id_token") or "").strip()
    id_payload = _decode_jwt_payload(id_token) if id_token else {}
    id_auth = id_payload.get("https://api.openai.com/auth") or {}
    organizations = id_auth.get("organizations") or []

    expires_at = (
        _parse_expired_time(account.get("expired") or "")
        or int(payload.get("exp") or 0)
    )
    account_type = account.get("type") or account.get("plan_tag") or "plus"

    return {
        "name": f"{account_type}-{email}" if email else f"{account_type}-{index:04d}",
        "platform": "openai",
        "type": "oauth",
        "credentials": {
            "access_token": access_token,
            "chatgpt_account_id": account_id,
            "chatgpt_user_id": auth_info.get("chatgpt_user_id") or "",
            "expires_at": expires_at,
            "expires_in": 864000,
            "organization_id": organizations[0]["id"] if organizations else "",
            "refresh_token": refresh_token,
        },
        "extra": {
            "email": email,
        },
        "concurrency": 10,
        "priority": 1,
        "rate_multiplier": 1,
        "auto_pause_on_expired": True,
    }


def push_to_sub2api(
    accounts: list[dict],
    sub2api_cfg: dict,
    *,
    log: Any = print,
) -> dict:
    """批量推送账号到 sub2api。

    sub2api_cfg 需要：base_url, token, skip_default_group_bind(可选, 默认True)。
    返回 sub2api 接口的响应 data 或错误字典。
    """
    base_url = str(sub2api_cfg.get("base_url") or "").rstrip("/")
    token = str(sub2api_cfg.get("token") or "")
    skip_bind = sub2api_cfg.get("skip_default_group_bind", True)
    push_group_id_raw = str(sub2api_cfg.get("push_group_id") or "").strip()
    push_group_id = int(push_group_id_raw) if push_group_id_raw.isdigit() else 0

    if not base_url or not token:
        return {"error": "sub2api 配置缺少 base_url 或 token"}

    sub_accounts = []
    skipped = 0
    for i, acc in enumerate(accounts):
        built = build_sub2api_account(acc, i + 1)
        if built:
            sub_accounts.append(built)
        else:
            skipped += 1

    if not sub_accounts:
        return {"error": "没有可推送的账号（全部缺少 access_token）", "skipped": skipped}

    payload = {
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxies": [],
        "accounts": sub_accounts,
    }

    # 自动检测是否需要 /api/v1 前缀：先尝试不加，如果返回 HTML 则加上
    url = f"{base_url}/admin/accounts/data"
    if "/api/" not in base_url:
        # 可能需要 /api/v1 前缀（反向代理后前端拦截了 /admin/ 路径）
        url_with_prefix = f"{base_url}/api/v1/admin/accounts/data"
    else:
        url_with_prefix = None
    # 其他 admin 端点
    accounts_url = f"{base_url}/admin/accounts"
    accounts_url_with_prefix = f"{base_url}/api/v1/admin/accounts" if ("/api/" not in base_url) else None
    bulk_update_url = f"{base_url}/admin/accounts/bulk-update"
    bulk_update_url_with_prefix = f"{base_url}/api/v1/admin/accounts/bulk-update" if ("/api/" not in base_url) else None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "x-api-key": token,
    }
    body = {
        "data": payload,
        "skip_default_group_bind": skip_bind,
    }

    try:
        log(f"[sub2api] POST {url}  accounts={len(sub_accounts)}")
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            r = client.post(url, json=body, headers=headers)
            ct = r.headers.get("content-type", "")
            # 若返回 HTML（前端路由拦截），自动尝试带 /api/v1 的路径
            if "text/html" in ct and url_with_prefix:
                log(f"[sub2api] 收到 HTML 响应，尝试带 /api/v1 前缀: {url_with_prefix}")
                r = client.post(url_with_prefix, json=body, headers=headers)
            # 推送成功后：如果配置了 push_group_id，则对导入的账号做一次批量分组绑定
            if r.status_code < 300 and push_group_id > 0:
                # 通过 email/name 搜索拿到 sub2api account_id
                account_ids: list[int] = []
                for item in sub_accounts:
                    key = (item.get("extra") or {}).get("email") or item.get("name") or ""
                    key = str(key).strip()
                    if not key:
                        continue
                    rr = client.get(
                        accounts_url,
                        headers=headers,
                        params={"page": 1, "page_size": 5, "search": key},
                    )
                    if "text/html" in rr.headers.get("content-type", "") and accounts_url_with_prefix:
                        rr = client.get(
                            accounts_url_with_prefix,
                            headers=headers,
                            params={"page": 1, "page_size": 5, "search": key},
                        )
                    if rr.status_code >= 400:
                        continue
                    try:
                        d = rr.json()
                    except Exception:
                        continue
                    if isinstance(d, dict) and d.get("code") == 0 and "data" in d:
                        d = d.get("data")
                    # 兼容 items/data/results
                    items = None
                    if isinstance(d, dict):
                        if isinstance(d.get("items"), list):
                            items = d.get("items")
                        elif isinstance(d.get("data"), list):
                            items = d.get("data")
                        elif isinstance(d.get("results"), list):
                            items = d.get("results")
                    if items is None and isinstance(d, list):
                        items = d
                    if not items:
                        continue
                    first = items[0] if isinstance(items[0], dict) else None
                    if not first:
                        continue
                    try:
                        aid = int(first.get("id") or 0)
                    except Exception:
                        aid = 0
                    if aid > 0:
                        account_ids.append(aid)

                if account_ids:
                    log(f"[sub2api] 批量绑定分组 group_id={push_group_id}  accounts={len(account_ids)}")
                    rr = client.post(
                        bulk_update_url,
                        headers=headers,
                        json={"account_ids": account_ids, "group_ids": [push_group_id]},
                    )
                    if "text/html" in rr.headers.get("content-type", "") and bulk_update_url_with_prefix:
                        rr = client.post(
                            bulk_update_url_with_prefix,
                            headers=headers,
                            json={"account_ids": account_ids, "group_ids": [push_group_id]},
                        )
                    if rr.status_code >= 400:
                        log(f"[sub2api] ⚠ 分组绑定失败 HTTP {rr.status_code} body[:200]={rr.text[:200]}")
        log(f"[sub2api] HTTP {r.status_code}  content-type={r.headers.get('content-type', '?')}  body[:{min(200, len(r.text))}]={r.text[:200]}")
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("message") or r.json().get("error") or r.text[:300]
            except Exception:
                detail = r.text[:300]
            return {"error": f"HTTP {r.status_code}: {detail}"}
        # 尝试解析 JSON; 部分 sub2api 版本在 import 成功时可能返回空 body 或纯文本
        body_text = r.text.strip()
        if not body_text:
            return {
                "ok": True,
                "account_created": len(sub_accounts),
                "account_failed": 0,
                "pushed": len(sub_accounts),
                "skipped": skipped,
                "push_group_id": push_group_id,
                "raw_status": r.status_code,
                "note": "服务器返回空 body，视为成功",
            }
        try:
            data = r.json()
        except Exception:
            return {
                "ok": r.status_code < 300,
                "pushed": len(sub_accounts),
                "skipped": skipped,
                "raw_status": r.status_code,
                "raw_body": body_text[:500],
                "note": "响应非 JSON，已按状态码判断",
            }
        if isinstance(data, dict) and data.get("code") == 0 and "data" in data:
            data = data["data"]
        if not isinstance(data, dict):
            return {
                "ok": r.status_code < 300,
                "pushed": len(sub_accounts),
                "skipped": skipped,
                "raw_status": r.status_code,
                "raw_body": str(data)[:500],
            }
        return {
            "ok": True,
            "account_created": data.get("account_created", 0),
            "account_failed": data.get("account_failed", 0),
            "proxy_created": data.get("proxy_created", 0),
            "proxy_reused": data.get("proxy_reused", 0),
            "proxy_failed": data.get("proxy_failed", 0),
            "pushed": len(sub_accounts),
            "skipped": skipped,
            "push_group_id": push_group_id,
        }
    except Exception as e:
        return {"error": f"请求失败: {type(e).__name__}: {str(e)[:200]}"}
