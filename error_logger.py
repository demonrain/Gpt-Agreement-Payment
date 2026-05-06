"""结构化错误日志写入器。

所有流水线阶段（注册 / 支付 / 后处理）的异常都写入
output/error_logs/YYYY-MM-DD.jsonl，每行一条 JSON 记录。
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path(os.environ.get("ERROR_LOG_DIR",
                                Path(__file__).resolve().parent / "output" / "error_logs"))

_MAX_TRACEBACK_LINES = 30


def _ensure_dir() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def log_error(
    phase: str,
    email: str = "",
    error: Exception | str | None = None,
    extra: dict | None = None,
) -> Path:
    """写一条错误日志，返回日志文件路径。

    phase: "registration" / "payment" / "gost" / "proxy" / ...
    """
    ts = datetime.now(timezone.utc)
    log_dir = _ensure_dir()
    log_file = log_dir / f"{ts.strftime('%Y-%m-%d')}.jsonl"

    tb = ""
    if isinstance(error, BaseException):
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        tb_lines = tb.strip().splitlines()
        if len(tb_lines) > _MAX_TRACEBACK_LINES:
            tb = "\n".join(tb_lines[-_MAX_TRACEBACK_LINES:])

    entry = {
        "ts": ts.isoformat(),
        "phase": phase,
        "email": email,
        "error": str(error)[:500] if error else "",
        "traceback": tb[:3000],
    }
    if extra:
        entry["extra"] = {k: str(v)[:200] for k, v in extra.items()}

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return log_file


def get_recent_errors(days: int = 1, limit: int = 50) -> list[dict]:
    """读取最近 N 天的错误日志。"""
    from datetime import timedelta

    log_dir = _ensure_dir()
    entries: list[dict] = []
    today = datetime.now(timezone.utc)

    for d in range(days):
        target = today - timedelta(days=d)
        fname = log_dir / f"{target.strftime('%Y-%m-%d')}.jsonl"
        if not fname.exists():
            continue
        try:
            for line in fname.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        except Exception:
            pass

    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return entries[:limit]
