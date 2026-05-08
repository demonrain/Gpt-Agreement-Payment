"""ADB 设备连接检测 preflight。

检查项：
  1. adb 可执行文件是否在 PATH
  2. 指定设备是否已连接
  3. WhatsApp 是否已安装
  4. WhatsApp 通知栏是否可读取

WSL/Docker 环境自动检测宿主机 IP，替换 127.0.0.1 为可达地址。
"""
from __future__ import annotations

import os
import re
import shutil
import socket as _sock
import subprocess
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ._common import CheckResult, PreflightResult, aggregate

_HOST_IP_CACHE_TTL_S = int(os.environ.get("GPT_PAY_HOST_IP_CACHE_TTL_S", "300") or 300)
_HOST_IP_CACHE: tuple[str, float] = ("", 0.0)
_ADB_TCP_SERIAL_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3}):(\d{1,5})\b")
_LAN_SCAN_DEFAULT_PORTS = (5555, 5557, 7555, 16348, 16384, 16416, 16448, 16480, 62001)


def _valid_ipv4(value: str | None) -> str | None:
    value = str(value or "").strip()
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if ip.version != 4 or ip.is_loopback or ip.is_unspecified:
        return None
    return value


def _valid_lan_ipv4(value: str | None) -> str | None:
    ip_text = _valid_ipv4(value)
    if not ip_text:
        return None
    ip = ipaddress.ip_address(ip_text)
    if ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return None
    if not ip.is_private:
        return None
    return ip_text


def _is_tcp_serial(serial: str) -> bool:
    match = _ADB_TCP_SERIAL_RE.fullmatch(str(serial or "").strip())
    if not match:
        return False
    host, port_text = match.groups()
    if not _valid_ipv4(host):
        return False
    try:
        port = int(port_text)
    except ValueError:
        return False
    return 1 <= port <= 65535


def _parse_tcp_serial(serial: str) -> tuple[str, int] | None:
    if not _is_tcp_serial(serial):
        return None
    host, port_text = _ADB_TCP_SERIAL_RE.fullmatch(serial.strip()).groups()  # type: ignore[union-attr]
    return host, int(port_text)


def _parse_port_list(value: str | None, default: tuple[int, ...] = _LAN_SCAN_DEFAULT_PORTS) -> list[int]:
    ports: list[int] = []
    raw = str(value or "").strip()
    tokens = re.split(r"[\s,;]+", raw) if raw else [str(p) for p in default]
    for token in tokens:
        if not token:
            continue
        try:
            port = int(token)
        except ValueError:
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    return ports or list(default)


def _to_bool(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _env_bool(name: str, default: bool = True) -> bool:
    return _to_bool(os.environ.get(name), default)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(errors="ignore").lower()
    except Exception:
        return False


def _read_resolv_nameserver() -> str | None:
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return None
    try:
        for line in resolv.read_text().splitlines():
            if line.strip().startswith("nameserver"):
                return _valid_ipv4(line.split()[1])
    except Exception:
        return None
    return None


def _detect_windows_host_ip_via_powershell(nameserver_ip: str | None = None) -> str | None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        return None
    try:
        ps = (
            "Get-NetIPAddress -AddressFamily IPv4 | "
            "Where-Object { $_.IPAddress -notlike '127.*' -and "
            "$_.IPAddress -notlike '169.254.*' -and "
            "$_.PrefixOrigin -ne 'WellKnown' } | "
            "Select-Object -ExpandProperty IPAddress"
        )
        r = subprocess.run(
            [powershell, "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    candidates = [
        ip for ip in (_valid_ipv4(line) for line in r.stdout.splitlines())
        if ip and ip != nameserver_ip
    ]
    if not candidates:
        return None
    if nameserver_ip:
        try:
            net = ipaddress.ip_network(f"{nameserver_ip}/24", strict=False)
            for ip in candidates:
                if ipaddress.ip_address(ip) in net:
                    return ip
        except ValueError:
            pass
    return candidates[0]


def _local_lan_ipv4s() -> list[str]:
    ips: list[str] = []
    hostname = _sock.gethostname()
    try:
        for family, _, _, _, sockaddr in _sock.getaddrinfo(hostname, None, family=_sock.AF_INET):
            if family != _sock.AF_INET:
                continue
            ip = _valid_lan_ipv4(sockaddr[0])
            if ip and ip not in ips:
                ips.append(ip)
    except OSError:
        pass

    try:
        with _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = _valid_lan_ipv4(sock.getsockname()[0])
            if ip and ip not in ips:
                ips.append(ip)
    except OSError:
        pass

    host_ip = _valid_lan_ipv4(_HOST_IP)
    if host_ip and host_ip not in ips:
        ips.append(host_ip)
    return ips


def _detect_host_ip() -> str | None:
    """WSL/Docker 环境下获取宿主机 IP（用于连接宿主机上的模拟器）。"""
    for key in ("GPT_PAY_ADB_HOST_IP", "WSL_ADB_HOST_IP", "ADB_HOST_IP", "WINDOWS_HOST_IP"):
        ip = _valid_ipv4(os.environ.get(key))
        if ip:
            return ip

    global _HOST_IP_CACHE
    cached_ip, cached_ts = _HOST_IP_CACHE
    now = time.monotonic()
    if cached_ip and now - cached_ts < _HOST_IP_CACHE_TTL_S:
        return cached_ip

    nameserver_ip = _read_resolv_nameserver()
    if _is_wsl():
        win_ip = _detect_windows_host_ip_via_powershell(nameserver_ip)
        if win_ip:
            _HOST_IP_CACHE = (win_ip, now)
            return win_ip
        if nameserver_ip:
            _HOST_IP_CACHE = (nameserver_ip, now)
        return nameserver_ip

    # Docker: host.docker.internal
    if os.path.exists("/.dockerenv"):
        return "host.docker.internal"
    if nameserver_ip:
        _HOST_IP_CACHE = (nameserver_ip, now)
    return nameserver_ip


_HOST_IP = _detect_host_ip()


def _known_emulator_ports(host_ip: str | None = None) -> dict[str, str]:
    """各模拟器常见 ADB 端口（WSL/Docker 用宿主机 IP，本机用 127.0.0.1）。"""
    host = host_ip or "127.0.0.1"
    return {
        "mumu6": f"{host}:7555",
        "mumu12_legacy": f"{host}:16348",
        "mumu12_0": f"{host}:16384",
        "mumu12_1": f"{host}:16416",
        "mumu12_2": f"{host}:16448",
        "mumu12_3": f"{host}:16480",
        "mumu12_adb0": f"{host}:5555",
        "mumu12_adb1": f"{host}:5557",
        "ldplayer": "emulator-5554",
        "nox": f"{host}:62001",
        "bluestacks": f"{host}:5555",
    }


KNOWN_EMULATOR_PORTS = _known_emulator_ports(_HOST_IP)


def _configured_lan_scan_subnets(value: str | None = None) -> list[ipaddress.IPv4Network]:
    raw = str(value if value is not None else os.environ.get("GPT_PAY_ADB_SCAN_SUBNETS") or "").strip()
    values = re.split(r"[\s,;]+", raw) if raw else []
    subnets: list[ipaddress.IPv4Network] = []

    for value in values:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            ip = _valid_lan_ipv4(value)
            if not ip:
                continue
            network = ipaddress.ip_network(f"{ip}/32", strict=False)
        if network.version == 4 and network.num_addresses <= 256 and network not in subnets:
            subnets.append(network)

    if subnets:
        return subnets

    for ip in _local_lan_ipv4s():
        try:
            network = ipaddress.ip_network(f"{ip}/24", strict=False)
        except ValueError:
            continue
        if network not in subnets:
            subnets.append(network)
    return subnets


def _lan_scan_settings(options: dict | None = None) -> dict:
    options = options or {}
    scan_subnets = options.get("scan_subnets")
    scan_ports = options.get("scan_ports")
    scan_lan = options.get("scan_lan")
    return {
        "enabled": _to_bool(scan_lan, _env_bool("GPT_PAY_ADB_SCAN_LAN", True)),
        "ports": _parse_port_list(str(scan_ports) if scan_ports is not None else os.environ.get("GPT_PAY_ADB_SCAN_PORTS")),
        "subnets": [str(net) for net in _configured_lan_scan_subnets(str(scan_subnets) if scan_subnets is not None else None)],
        "timeout_s": _env_float("GPT_PAY_ADB_SCAN_TIMEOUT_S", 0.2, 0.05, 2.0),
        "workers": _env_int("GPT_PAY_ADB_SCAN_WORKERS", 64, 1, 256),
    }


def _run_adb(serial: str, *args: str, timeout: int = 10) -> tuple[int, str, str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", "adb not found"
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except Exception as e:
        return -3, "", str(e)


def _read_mdns_adb_services() -> list[str]:
    """Return TCP ADB endpoints advertised by Android wireless debugging."""
    rc, out, _ = _run_adb("", "mdns", "services", timeout=5)
    if rc != 0 or not out:
        return []

    endpoints: list[str] = []
    for line in out.splitlines():
        if "_adb-tls-connect._tcp" not in line and "_adb._tcp" not in line:
            continue
        for host, port_text in _ADB_TCP_SERIAL_RE.findall(line):
            serial = f"{host}:{port_text}"
            if _is_tcp_serial(serial) and serial not in endpoints:
                endpoints.append(serial)
    return endpoints


def _can_open_tcp(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with _sock.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _connect_tcp_serials(serials: list[str], timeout: int = 5) -> list[str]:
    connected: list[str] = []
    for serial in serials:
        parsed = _parse_tcp_serial(serial)
        if not parsed:
            continue
        host, port = parsed
        if not _can_open_tcp(host, port, timeout=0.5):
            continue
        _run_adb("", "connect", serial, timeout=timeout)
        connected.append(serial)
    return connected


def _scan_lan_adb_tcp(settings: dict | None = None) -> list[str]:
    """Scan configured/local LAN subnets for open TCP ADB ports."""
    settings = settings or _lan_scan_settings()
    if not settings.get("enabled", True):
        return []

    ports = [int(p) for p in settings.get("ports") or _LAN_SCAN_DEFAULT_PORTS]
    timeout_s = float(settings.get("timeout_s") or 0.2)
    workers = int(settings.get("workers") or 64)

    subnets: list[ipaddress.IPv4Network] = []
    for value in settings.get("subnets") or []:
        try:
            subnet = ipaddress.ip_network(str(value), strict=False)
        except ValueError:
            continue
        if subnet.version == 4 and subnet.num_addresses <= 256:
            subnets.append(subnet)

    endpoints: list[tuple[str, int]] = []
    for subnet in subnets:
        for ip in subnet.hosts() if subnet.num_addresses > 1 else [subnet.network_address]:
            ip_text = str(ip)
            if not _valid_lan_ipv4(ip_text):
                continue
            for port in ports:
                endpoints.append((ip_text, port))

    if not endpoints:
        return []

    found: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(endpoints)))) as executor:
        future_to_endpoint = {
            executor.submit(_can_open_tcp, host, port, timeout_s): (host, port)
            for host, port in endpoints
        }
        for future in as_completed(future_to_endpoint):
            host, port = future_to_endpoint[future]
            try:
                is_open = future.result()
            except OSError:
                is_open = False
            if is_open:
                serial = f"{host}:{port}"
                if serial not in found:
                    found.append(serial)

    return found


def check(body: dict) -> PreflightResult:
    serial = str(body.get("adb_serial") or "").strip()
    checks: list[CheckResult] = []

    # 1. adb 是否可用
    adb_path = shutil.which("adb")
    if adb_path:
        checks.append(CheckResult(
            name="adb_binary",
            status="ok",
            message=f"adb 已找到: {adb_path}",
        ))
    else:
        checks.append(CheckResult(
            name="adb_binary",
            status="fail",
            message="adb 不在 PATH 中，请安装 Android SDK Platform-Tools",
        ))
        return aggregate(checks)

    # 2. 尝试连接（对 IP:PORT 格式先 adb connect）
    if serial and _is_tcp_serial(serial):
        rc, out, err = _run_adb("", "connect", serial)
        if rc == 0 and "connected" in out.lower():
            checks.append(CheckResult(
                name="adb_connect",
                status="ok",
                message=f"adb connect {serial} 成功",
                details=out.strip()[:200],
            ))
        else:
            checks.append(CheckResult(
                name="adb_connect",
                status="warn",
                message=f"adb connect {serial} 结果不确定",
                details=(out + err).strip()[:200],
            ))

    # 3. 设备是否在线
    rc, out, _ = _run_adb("", "devices")
    if rc != 0:
        checks.append(CheckResult(
            name="adb_devices",
            status="fail",
            message="adb devices 命令失败",
        ))
        return aggregate(checks)

    all_devices = [
        d["serial"] for d in _parse_device_lines(out)
        if d["state"] == "device"
    ]

    if serial:
        found = any(serial in d or d in serial for d in all_devices)
        if found:
            checks.append(CheckResult(
                name="device_online",
                status="ok",
                message=f"设备 {serial} 在线",
                details=f"所有设备: {', '.join(all_devices)}",
            ))
        else:
            checks.append(CheckResult(
                name="device_online",
                status="fail",
                message=f"设备 {serial} 未找到",
                details=f"在线设备: {', '.join(all_devices) or '(无)'}",
            ))
            return aggregate(checks)
    elif all_devices:
        serial = all_devices[0]
        checks.append(CheckResult(
            name="device_online",
            status="ok",
            message=f"自动检测到设备: {serial}",
            details=f"所有设备: {', '.join(all_devices)}",
        ))
    else:
        checks.append(CheckResult(
            name="device_online",
            status="fail",
            message="未检测到任何 ADB 设备",
            details="请确认模拟器已启动且 ADB 调试已开启",
        ))
        return aggregate(checks)

    # 4. WhatsApp 是否已安装
    rc, out, _ = _run_adb(serial, "shell", "pm", "list", "packages", "com.whatsapp")
    wa_installed = "com.whatsapp" in out
    if wa_installed:
        checks.append(CheckResult(
            name="whatsapp_installed",
            status="ok",
            message="WhatsApp 已安装",
        ))
    else:
        checks.append(CheckResult(
            name="whatsapp_installed",
            status="fail",
            message="WhatsApp 未安装，请在模拟器中安装 WhatsApp 并登录",
        ))
        return aggregate(checks)

    # 5. 通知栏读取测试
    rc, out, err = _run_adb(serial, "shell", "dumpsys", "notification", "--noredact")
    if rc == 0 and len(out) > 50:
        wa_notif = "com.whatsapp" in out.lower()
        checks.append(CheckResult(
            name="notification_read",
            status="ok",
            message="通知栏可读取" + ("，检测到 WhatsApp 通知" if wa_notif else "（暂无 WhatsApp 通知）"),
            details=f"dumpsys 输出长度: {len(out)} 字符",
        ))
    else:
        checks.append(CheckResult(
            name="notification_read",
            status="warn",
            message="通知栏读取异常",
            details=(err or out)[:200],
        ))

    return aggregate(checks)


def _auto_connect_known_ports(known_ports: dict[str, str] | None = None) -> None:
    """尝试自动连接已知 TCP ADB 端口。"""
    _connect_tcp_serials(list((known_ports or KNOWN_EMULATOR_PORTS).values()), timeout=5)


def _disconnect_offline_tcp_devices(devices: list[dict]) -> None:
    """清理 stale TCP ADB 连接，避免旧 offline 设备占住扫描结果。"""
    for dev in devices:
        serial = str(dev.get("serial") or "")
        if dev.get("state") != "offline":
            continue
        if not _is_tcp_serial(serial):
            continue
        _run_adb("", "disconnect", serial, timeout=5)


def _parse_device_lines(raw: str) -> list[dict]:
    devices = []
    seen_header = False
    for line in raw.strip().splitlines():
        if line.strip().startswith("List of devices"):
            seen_header = True
            continue
        if not seen_header:
            continue
        parts = line.split()
        if len(parts) >= 2:
            model = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
            devices.append({
                "serial": parts[0],
                "state": parts[1],
                "model": model,
            })
    return devices


def list_devices(options: dict | None = None) -> dict:
    """列出所有 ADB 设备及其状态，WSL 下自动探测已知模拟器端口。"""
    global _HOST_IP, KNOWN_EMULATOR_PORTS
    _HOST_IP = _detect_host_ip()
    KNOWN_EMULATOR_PORTS = _known_emulator_ports(_HOST_IP)
    lan_scan = _lan_scan_settings(options)

    adb_path = shutil.which("adb")
    if not adb_path:
        return {
            "ok": False,
            "error": "adb not in PATH, 请在 WSL 中运行: sudo apt install android-tools-adb",
            "devices": [],
        }

    rc, out, err = _run_adb("", "devices", "-l")
    if rc != 0:
        return {"ok": False, "error": err[:200], "devices": []}

    devices = _parse_device_lines(out)

    # 如果没有 device 状态的设备，自动探测已知 TCP ADB 端口
    online = [d for d in devices if d["state"] == "device"]
    if not online:
        _disconnect_offline_tcp_devices(devices)
        _auto_connect_known_ports(KNOWN_EMULATOR_PORTS)
        rc2, out2, _ = _run_adb("", "devices", "-l")
        if rc2 == 0:
            devices = _parse_device_lines(out2)

    online = [d for d in devices if d["state"] == "device"]
    if not online:
        _connect_tcp_serials(_read_mdns_adb_services(), timeout=5)
        rc3, out3, _ = _run_adb("", "devices", "-l")
        if rc3 == 0:
            devices = _parse_device_lines(out3)

    online = [d for d in devices if d["state"] == "device"]
    if not online:
        _connect_tcp_serials(_scan_lan_adb_tcp(lan_scan), timeout=5)
        rc4, out4, _ = _run_adb("", "devices", "-l")
        if rc4 == 0:
            devices = _parse_device_lines(out4)

    return {
        "ok": True,
        "devices": devices,
        "known_ports": KNOWN_EMULATOR_PORTS,
        "host_ip": _HOST_IP,
        "lan_scan": {
            "enabled": lan_scan["enabled"],
            "subnets": lan_scan["subnets"],
            "ports": lan_scan["ports"],
        },
        "hint": (
            f"WSL 环境检测到宿主机 IP: {_HOST_IP}，"
            f"模拟器端口请使用 {_HOST_IP}:<port>；"
            "局域网设备可用 GPT_PAY_ADB_SCAN_SUBNETS 指定扫描网段"
        ) if _HOST_IP else None,
    }
