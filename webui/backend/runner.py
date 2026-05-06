"""单 active-run 的 pipeline 进程控制器。

封装 `xvfb-run -a python pipeline.py [args]` 子进程：spawn / 流式收 stdout
到环形日志缓冲 / SIGTERM-优先 stop / 暴露 status + log 给路由层。

支持自动重启：子进程非零退出时自动重新拉起（可配置重启次数与间隔），
确保无人值守场景下不会因单次崩溃导致整个流水线停止。

GoPay 模式下额外支持 OTP 中转：默认通过 WebUI 内部 HTTP endpoint
把 WhatsApp / 手动补录 OTP 写入 SQLite，gopay.py 轮询该 endpoint。
保留 `GOPAY_OTP_REQUEST path=<file>` 旧格式识别，只作为显式 legacy
file provider 的兼容 fallback。
"""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from . import settings as s
from . import wa_relay
from .runner_helpers import build_cmd
from .runner_helpers import read_gopay_otp_source as _read_gopay_otp_source
from .runner_helpers import detect_otp_wait_target as _detect_otp_wait_target
from .runner_helpers import gopay_auto_otp_enabled as _gopay_auto_otp_enabled


_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_started_at: Optional[float] = None
_ended_at: Optional[float] = None
_exit_code: Optional[int] = None
_cmd: Optional[list[str]] = None
_mode: Optional[str] = None
_log_lines: list[dict] = []  # {seq, ts, line}
_seq_counter = 0
_otp_file: Optional[Path] = None       # legacy file provider path, if used
_otp_to_db: bool = False               # True when gopay.py waits on WebUI SQLite OTP endpoint
_otp_pending: bool = False             # set when gopay.py asks/waits for OTP
_otp_file_is_temp: bool = False

# 自动重启配置
_auto_restart: bool = False
_restart_delay_s: int = 15
_max_restarts: int = 0              # 0 = 无限重启
_restart_count: int = 0
_stop_requested: bool = False       # stop() 主动停止时不自动重启
_start_kwargs: dict = {}            # 缓存 start() 参数用于重启




def status() -> dict:
    global _proc
    is_running = _proc is not None and _proc.poll() is None
    return {
        "running": is_running,
        "started_at": _started_at,
        "ended_at": _ended_at,
        "exit_code": _exit_code if not is_running else None,
        "cmd": _cmd,
        "mode": _mode,
        "pid": _proc.pid if is_running and _proc else None,
        "log_count": _seq_counter,
        "otp_pending": _otp_pending,
        "auto_restart": _auto_restart,
        "restart_count": _restart_count,
    }


def _maybe_auto_restart() -> None:
    """进程退出后检查是否需要自动重启。"""
    global _restart_count
    if not _auto_restart or _stop_requested:
        return
    if _exit_code == 0:
        return
    if _max_restarts > 0 and _restart_count >= _max_restarts:
        _append_log(f"[runner] 已达最大重启次数 ({_max_restarts})，停止自动重启")
        return

    _restart_count += 1
    _append_log(
        f"[runner] 进程异常退出 (code={_exit_code})，"
        f"{_restart_delay_s}s 后自动重启 (第 {_restart_count} 次)"
    )
    threading.Thread(target=_delayed_restart, daemon=True).start()


def _delayed_restart() -> None:
    time.sleep(_restart_delay_s)
    if _stop_requested:
        return
    try:
        _spawn_process()
    except Exception as e:
        _append_log(f"[runner] 自动重启失败: {e}")


def _append_log(msg: str) -> None:
    global _seq_counter
    with _lock:
        _seq_counter += 1
        _log_lines.append({"seq": _seq_counter, "ts": time.time(), "line": msg})


def _spawn_process() -> None:
    """内部：拉起子进程并启动 drain 线程（自动重启时调用）。"""
    global _proc, _started_at, _ended_at, _exit_code
    global _otp_to_db, _otp_pending, _otp_file_is_temp

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    kw = _start_kwargs
    if kw.get("gopay"):
        _otp_src = _read_gopay_otp_source()
        if _otp_src not in ("adb", "appium"):
            env["WEBUI_GOPAY_OTP_URL"] = wa_relay.otp_url()

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return
        _started_at = time.time()
        _ended_at = None
        _exit_code = None
        _otp_to_db = False
        _otp_file_is_temp = False
        _otp_pending = False

        proc = subprocess.Popen(
            _cmd,
            cwd=str(s.ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        _proc = proc

    _append_log(f"[runner] 进程已启动 PID={proc.pid}")
    threading.Thread(target=_drain, args=(proc,), daemon=True).start()


def start(*, mode: str, paypal: bool = True, batch: int = 0, workers: int = 3,
          self_dealer: int = 0, register_only: bool = False, pay_only: bool = False,
          gopay: bool = False, count: int = 0, pay_only_email: str = "",
          auto_restart: bool = True, restart_delay: int = 15,
          max_restarts: int = 0) -> dict:
    global _proc, _started_at, _ended_at, _exit_code, _cmd, _mode
    global _log_lines, _seq_counter, _otp_file, _otp_to_db, _otp_pending, _otp_file_is_temp
    global _auto_restart, _restart_delay_s, _max_restarts, _restart_count
    global _stop_requested, _start_kwargs
    with _lock:
        if _proc is not None and _proc.poll() is None:
            raise RuntimeError("a pipeline is already running")

        otp_p: Optional[Path] = None

        cmd = build_cmd(mode, paypal, batch, workers, self_dealer,
                        register_only, pay_only, gopay=gopay,
                        gopay_otp_file="", count=count,
                        pay_only_email=pay_only_email)

        _log_lines = []
        _seq_counter = 0
        _started_at = time.time()
        _ended_at = None
        _exit_code = None
        _cmd = cmd
        _mode = mode
        _otp_file = otp_p
        _otp_to_db = False
        _otp_file_is_temp = otp_p is not None
        _otp_pending = False

        _auto_restart = auto_restart
        _restart_delay_s = restart_delay
        _max_restarts = max_restarts
        _restart_count = 0
        _stop_requested = False
        _start_kwargs = {
            "mode": mode, "paypal": paypal, "gopay": gopay,
        }

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if gopay:
            _otp_src = _read_gopay_otp_source()
            if _otp_src not in ("adb", "appium"):
                env["WEBUI_GOPAY_OTP_URL"] = wa_relay.otp_url()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(s.ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
        except FileNotFoundError as e:
            _ended_at = time.time()
            _exit_code = -1
            raise RuntimeError(f"failed to spawn: {e}") from e
        _proc = proc

        threading.Thread(target=_drain, args=(proc,), daemon=True).start()
    return status()




def _drain(proc: subprocess.Popen) -> None:
    global _ended_at, _exit_code, _seq_counter, _log_lines
    global _otp_pending, _otp_file, _otp_to_db, _otp_file_is_temp
    try:
        if proc.stdout is None:
            return
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            with _lock:
                _seq_counter += 1
                _log_lines.append({"seq": _seq_counter, "ts": time.time(), "line": line})
                if len(_log_lines) > 3000:
                    _log_lines = _log_lines[-2000:]
                wait_kind, wait_path = _detect_otp_wait_target(line)
                if wait_kind:
                    _otp_to_db = wait_kind == "db"
                    _otp_file = wait_path
                    _otp_file_is_temp = _otp_file_is_temp or "GOPAY_OTP_REQUEST" in line
                    _otp_pending = True
    finally:
        proc.wait()
        with _lock:
            _ended_at = time.time()
            _exit_code = proc.returncode
            _otp_pending = False
            if _otp_file is not None:
                try:
                    _otp_file.unlink(missing_ok=True)
                except Exception:
                    pass
        _maybe_auto_restart()


def stop() -> dict:
    global _proc, _stop_requested
    with _lock:
        _stop_requested = True
        proc = _proc
        if proc is None or proc.poll() is not None:
            return status()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return status()


def submit_otp(value: str) -> dict:
    """Front-end calls this with the OTP user typed. Stores it in DB by default."""
    global _otp_pending
    with _lock:
        if not _otp_pending:
            raise RuntimeError("no OTP currently requested")
        path = _otp_file
        use_db = _otp_to_db
    if use_db:
        wa_relay.submit_manual_otp(value)
    else:
        if path is None:
            raise RuntimeError("no OTP file currently requested")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value.strip(), encoding="utf-8")
    with _lock:
        _otp_pending = False
    return status()


def get_lines_since(since_seq: int = 0, limit: int = 1000) -> list[dict]:
    with _lock:
        return [e for e in _log_lines if e["seq"] > since_seq][:limit]


def get_tail(n: int = 200) -> list[dict]:
    with _lock:
        return _log_lines[-n:]
