"""gost 代理中继管理器。

webui 启动时自动读取 config.paypal.json 的 webshare 配置，
若 enabled=True 且本地 listen_port 无监听，自动从 Webshare API
获取代理并拉起 gost（SOCKS5 + HTTP 双端口）。
"""
from __future__ import annotations

import json
import os
import signal
import socket as _sock
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import settings as s

_CLASH_PORTS = (7897, 7890, 7891)


def _port_listening(port: int) -> bool:
    try:
        with _sock.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def _resolve_outbound_proxy() -> str:
    """优先环境变量，WSL 下回退探测宿主 Clash。"""
    env = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
           or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
    if env:
        return env
    if not os.environ.get("WSL_DISTRO_NAME"):
        return ""
    try:
        with open("/proc/net/route") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "00000000":
                    h = parts[2]
                    host = ".".join(
                        str(int(h[i:i + 2], 16)) for i in (6, 4, 2, 0)
                    )
                    for port in _CLASH_PORTS:
                        try:
                            conn = _sock.create_connection((host, port), timeout=1)
                            conn.close()
                            return f"http://{host}:{port}"
                        except OSError:
                            continue
    except OSError:
        pass
    return ""


_COUNTRY_ALIAS = {"UK": "GB", "USA": "US"}


def _normalize_country(code: str) -> str:
    c = code.strip().upper()
    return _COUNTRY_ALIAS.get(c, c)


class _WebshareClient:
    """Webshare.io API v2 最小客户端（仅用于获取代理信息）。"""

    BASE = "https://proxy.webshare.io/api/v2"

    def __init__(self, api_key: str, timeout_s: int = 30):
        self.api_key = api_key.strip()
        self.timeout_s = timeout_s
        proxy = _resolve_outbound_proxy()
        handler = urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy} if proxy else {}
        )
        self._opener = urllib.request.build_opener(handler)

    def _req(self, path: str, method: str = "GET"):
        req = urllib.request.Request(
            f"{self.BASE}{path}",
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        return self._opener.open(req, timeout=self.timeout_s)

    def _list_proxies(self, extra_qs: str = "") -> list[dict]:
        for mode in ("backbone", "direct"):
            qs = f"mode={mode}&page=1&page_size=5"
            if extra_qs:
                qs += f"&{extra_qs}"
            try:
                with self._req(f"/proxy/list/?{qs}") as r:
                    data = json.loads(r.read().decode())
                results = data.get("results") or []
                if results:
                    return results
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    continue
                raise
        return []

    def get_current_proxy(self) -> dict:
        results = self._list_proxies()
        if not results:
            raise RuntimeError("Webshare 代理列表为空")
        return results[0]

    def get_proxy_by_country(self, country_code: str) -> dict | None:
        cc = _normalize_country(country_code)
        results = self._list_proxies(extra_qs=f"country_code__in={cc}")
        for p in results:
            if p.get("valid"):
                return p
        return results[0] if results else None


def _swap_gost_relay(
    new_ip: str,
    new_port: int,
    username: str,
    password: str,
    listen_port: int = 18898,
    upstream_scheme: str = "http",
) -> None:
    """停旧 gost，拉新 gost（SOCKS5 :listen_port + HTTP :listen_port+1）。"""
    listen_pat = f"-L=socks5://:{listen_port}"
    try:
        out = subprocess.check_output(["pgrep", "-af", "gost"], text=True)
    except subprocess.CalledProcessError:
        out = ""

    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and listen_pat in parts[1]:
            try:
                os.kill(int(parts[0]), signal.SIGTERM)
                print(f"[gost] 停止旧 gost PID={parts[0]}")
            except Exception as e:
                print(f"[gost] 杀 PID={parts[0]} 失败: {e}")

    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            ck = subprocess.run(
                ["ss", "-ltn", f"sport = :{listen_port}"],
                capture_output=True, text=True, timeout=3,
            )
            if f":{listen_port}" not in ck.stdout:
                break
        except Exception:
            break
        time.sleep(0.3)

    upstream = f"{upstream_scheme}://{username}:{password}@{new_ip}:{new_port}"
    http_port = listen_port + 1
    cmd = ["gost", f"-L=socks5://:{listen_port}", f"-L=http://:{http_port}"]
    local_proxy = _resolve_outbound_proxy()
    if local_proxy:
        cmd.append(f"-F={local_proxy}")
        print(f"[gost] WSL 链式代理：先过 {local_proxy}")
    cmd.append(f"-F={upstream}")

    log_path = f"/tmp/gost-{listen_port}.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        p = subprocess.Popen(
            cmd, stdout=fd, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    finally:
        os.close(fd)

    time.sleep(1.5)
    if p.poll() is not None:
        raise RuntimeError(f"gost 启动即退出，见 {log_path}")
    print(f"[gost] 启动中继 PID={p.pid}  upstream={new_ip}:{new_port}")


def ensure_gost_alive() -> bool:
    """读取 config.paypal.json 的 webshare 配置，自动拉起 gost。

    返回 True 表示 gost 已在运行或成功拉起，False 表示不需要或失败。
    """
    cfg_path = s.PAY_CONFIG_PATH
    if not cfg_path.exists():
        print("[gost] config.paypal.json 不存在，跳过")
        return False

    try:
        card_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[gost] 读取配置失败: {e}")
        return False

    ws_cfg = (card_cfg or {}).get("webshare") or {}
    if not ws_cfg.get("enabled"):
        print("[gost] webshare 未启用，跳过")
        return False

    api_key = (ws_cfg.get("api_key") or "").strip()
    listen_port = int(ws_cfg.get("gost_listen_port", 18898))
    if not api_key:
        print("[gost] webshare api_key 为空，跳过")
        return False

    lock_country = _normalize_country(ws_cfg.get("lock_country") or "")

    if _port_listening(listen_port):
        print(f"[gost] :{listen_port} 已有监听，无需重启")
        return True

    print(f"[gost] :{listen_port} 无监听，自动拉起")

    try:
        client = _WebshareClient(api_key)
    except Exception as e:
        print(f"[gost] WebshareClient 初始化失败: {e}")
        return False

    px = None
    try:
        if lock_country:
            px = client.get_proxy_by_country(lock_country)
        if not px:
            px = client.get_current_proxy()
    except Exception as e:
        print(f"[gost] 查询 Webshare 代理失败: {e}")
        return False

    upstream_scheme = str(ws_cfg.get("gost_upstream_scheme", "http"))
    proxy_host = px.get("proxy_address") or "p.webshare.io"
    proxy_port = int(px.get("port") or 80)
    if not px.get("proxy_address"):
        proxy_port = 80

    try:
        _swap_gost_relay(
            proxy_host, proxy_port,
            px["username"], px["password"],
            listen_port=listen_port,
            upstream_scheme=upstream_scheme,
        )
    except Exception as e:
        print(f"[gost] 拉起失败: {e}")
        return False

    print(
        f"[gost] 代理国家={px.get('country_code', '?')} "
        f"upstream={proxy_host}:{proxy_port}"
    )
    return True
