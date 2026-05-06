import os
import socket
from typing import Literal
from pydantic import BaseModel

Status = Literal["ok", "warn", "fail"]

_CLASH_PORTS = (7897, 7890, 7891)


class CheckResult(BaseModel):
    name: str
    status: Status
    message: str
    details: str | None = None


class PreflightResult(BaseModel):
    status: Status
    message: str
    details: str | None = None
    checks: list[CheckResult] = []


def aggregate(checks: list[CheckResult]) -> PreflightResult:
    if any(c.status == "fail" for c in checks):
        agg = "fail"
    elif any(c.status == "warn" for c in checks):
        agg = "warn"
    else:
        agg = "ok"
    msg = f"{sum(1 for c in checks if c.status == 'ok')}/{len(checks)} ok"
    return PreflightResult(status=agg, message=msg, checks=checks)


def _wsl_host_ip() -> str | None:
    """从 /proc/net/route 默认路由解析 Windows 宿主 IP"""
    try:
        with open("/proc/net/route") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "00000000":
                    h = parts[2]
                    return ".".join(
                        str(int(h[i:i + 2], 16)) for i in (6, 4, 2, 0)
                    )
    except OSError:
        pass
    return None


def _probe_wsl_host_proxy() -> str | None:
    """WSL 下探测 Windows 宿主常见 Clash 端口"""
    host = _wsl_host_ip()
    if not host:
        return None
    for port in _CLASH_PORTS:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return f"http://{host}:{port}"
        except OSError:
            continue
    return None


def resolve_system_proxy() -> str | None:
    """解析系统代理：优先环境变量，WSL 下回退探测宿主 Clash"""
    env = (os.environ.get("HTTPS_PROXY")
           or os.environ.get("https_proxy")
           or os.environ.get("HTTP_PROXY")
           or os.environ.get("http_proxy"))
    if env:
        return env
    if os.environ.get("WSL_DISTRO_NAME"):
        return _probe_wsl_host_proxy()
    return None
