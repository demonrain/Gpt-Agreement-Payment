from webui.backend.preflight import adb


def test_detect_host_ip_uses_explicit_env_override(monkeypatch):
    monkeypatch.setenv("WSL_ADB_HOST_IP", "192.168.0.88")

    assert adb._detect_host_ip() == "192.168.0.88"


def test_detect_host_ip_prefers_windows_ip_over_bridge_gateway(monkeypatch):
    for key in ("GPT_PAY_ADB_HOST_IP", "WSL_ADB_HOST_IP", "ADB_HOST_IP", "WINDOWS_HOST_IP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(adb, "_is_wsl", lambda: True, raising=False)
    monkeypatch.setattr(adb, "_read_resolv_nameserver", lambda: "192.168.0.1", raising=False)
    monkeypatch.setattr(
        adb,
        "_detect_windows_host_ip_via_powershell",
        lambda nameserver_ip=None: "192.168.0.88",
        raising=False,
    )

    assert adb._detect_host_ip() == "192.168.0.88"


def test_detect_host_ip_uses_cache_to_avoid_repeated_windows_network_enum(monkeypatch):
    for key in ("GPT_PAY_ADB_HOST_IP", "WSL_ADB_HOST_IP", "ADB_HOST_IP", "WINDOWS_HOST_IP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(adb, "_is_wsl", lambda: True, raising=False)
    monkeypatch.setattr(adb, "_read_resolv_nameserver", lambda: "192.168.0.1", raising=False)
    monkeypatch.setattr(adb, "_HOST_IP_CACHE", ("", 0), raising=False)

    calls = []

    def fake_detect_windows_host_ip_via_powershell(nameserver_ip=None):
        calls.append(nameserver_ip)
        return "192.168.0.88"

    monkeypatch.setattr(
        adb,
        "_detect_windows_host_ip_via_powershell",
        fake_detect_windows_host_ip_via_powershell,
        raising=False,
    )

    assert adb._detect_host_ip() == "192.168.0.88"
    assert adb._detect_host_ip() == "192.168.0.88"
    assert calls == ["192.168.0.1"]


def test_list_devices_auto_connects_known_ports_when_no_online_device(monkeypatch):
    monkeypatch.setattr(adb.shutil, "which", lambda name: "adb" if name == "adb" else None)

    outputs = iter([
        (0, "List of devices attached\n\n", ""),
        (0, "List of devices attached\n127.0.0.1:7555 device model:MuMu\n", ""),
    ])
    calls = []

    def fake_run_adb(serial, *args, timeout=10):
        if args == ("devices", "-l"):
            return next(outputs)
        return 0, "", ""

    def fake_auto_connect_known_ports(_known_ports=None):
        calls.append("auto-connect")

    monkeypatch.setattr(adb, "_HOST_IP", None)
    monkeypatch.setattr(adb, "_detect_host_ip", lambda: None)
    monkeypatch.setattr(adb, "_run_adb", fake_run_adb)
    monkeypatch.setattr(adb, "_auto_connect_known_ports", fake_auto_connect_known_ports)

    result = adb.list_devices()

    assert calls == ["auto-connect"]
    assert result["ok"] is True
    assert result["devices"] == [
        {"serial": "127.0.0.1:7555", "state": "device", "model": "MuMu"}
    ]


def test_parse_device_lines_ignores_adb_daemon_banner():
    raw = """* daemon not running; starting now at tcp:5037
* daemon started successfully
List of devices attached
127.0.0.1:7555 device product:mumu model:MuMu_12 transport_id:1
"""

    assert adb._parse_device_lines(raw) == [
        {"serial": "127.0.0.1:7555", "state": "device", "model": "MuMu_12"}
    ]


def test_known_ports_include_mumu12_16348_port():
    assert "127.0.0.1:16348" in adb.KNOWN_EMULATOR_PORTS.values()


def test_list_devices_disconnects_offline_tcp_devices_before_auto_connect(monkeypatch):
    monkeypatch.setattr(adb.shutil, "which", lambda name: "adb" if name == "adb" else None)
    monkeypatch.setattr(adb, "_HOST_IP", "172.24.32.1")
    monkeypatch.setattr(adb, "_detect_host_ip", lambda: "172.24.32.1")

    outputs = iter([
        (
            0,
            "List of devices attached\n"
            "172.24.32.1:16416 offline product:Lange model:LGE_AN10\n"
            "172.24.32.1:5557 offline\n",
            "",
        ),
        (
            0,
            "List of devices attached\n"
            "172.24.32.1:16348 device product:Lange model:LGE_AN10\n",
            "",
        ),
    ])
    calls = []

    def fake_run_adb(serial, *args, timeout=10):
        calls.append((serial, args))
        if args == ("devices", "-l"):
            return next(outputs)
        return 0, "", ""

    monkeypatch.setattr(adb, "_run_adb", fake_run_adb)
    monkeypatch.setattr(adb._sock, "create_connection", lambda endpoint, timeout=0.5: _FakeSocket())

    result = adb.list_devices()

    assert ("", ("disconnect", "172.24.32.1:16416")) in calls
    assert ("", ("disconnect", "172.24.32.1:5557")) in calls
    assert ("", ("connect", "172.24.32.1:16348")) in calls
    assert result["devices"] == [
        {"serial": "172.24.32.1:16348", "state": "device", "model": "LGE_AN10"}
    ]


def test_list_devices_refreshes_wsl_host_ip_for_known_ports(monkeypatch):
    monkeypatch.setattr(adb.shutil, "which", lambda name: "adb" if name == "adb" else None)
    monkeypatch.setattr(adb, "_HOST_IP", "172.24.32.1")
    monkeypatch.setattr(adb, "_detect_host_ip", lambda: "172.24.40.1")

    outputs = iter([
        (0, "List of devices attached\n\n", ""),
        (0, "List of devices attached\n172.24.40.1:5555 device model:MuMu\n", ""),
    ])
    connected = []

    def fake_run_adb(serial, *args, timeout=10):
        if args == ("devices", "-l"):
            return next(outputs)
        if args[0] == "connect":
            connected.append(args[1])
        return 0, "", ""

    monkeypatch.setattr(adb, "_run_adb", fake_run_adb)
    monkeypatch.setattr(adb._sock, "create_connection", lambda endpoint, timeout=0.5: _FakeSocket())

    result = adb.list_devices()

    assert "172.24.40.1:5555" in connected
    assert result["host_ip"] == "172.24.40.1"
    assert result["known_ports"]["mumu12_legacy"] == "172.24.40.1:16348"
    assert result["devices"] == [
        {"serial": "172.24.40.1:5555", "state": "device", "model": "MuMu"}
    ]


class _FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
