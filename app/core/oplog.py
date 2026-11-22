"""导出日志：每切出一个片段就追加一条，**不轮转、不设上限**。

排查「为什么这段导出来不对」时，光看进度条没用，需要知道：
用的是哪条源、切点吸附到哪一帧、实际下发的 ffmpeg 命令是什么、
跑了多久、退出码和 stderr 尾部。所以这里一条记录把这些全写上。

格式是 JSON Lines（一行一个 JSON）。好处是追加写不会互相踩、能直接
grep、也能被脚本按字段读出来做统计。

日志写到 `<程序目录>/logs/export.log`。程序目录不可写时（例如装进
Program Files）自动退到 `%TEMP%/M4SMerge/logs/`，绝不因为写日志失败
影响导出本身。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from .settings import APP_NAME, app_root

_LOCK = threading.Lock()
_resolved: Path | None = None
_failed = False


def _candidates() -> list[Path]:
    out = [app_root() / "logs"]
    try:
        out.append(Path(os.environ.get("TEMP") or os.environ.get("TMP")
                        or __import__("tempfile").gettempdir()) / APP_NAME / "logs")
    except Exception:                       # noqa: BLE001
        pass
    return out


def log_dir() -> Path:
    """日志目录。第一次调用时确定，之后复用。"""
    global _resolved
    if _resolved is not None:
        return _resolved
    for d in _candidates():
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_test"
            probe.write_bytes(b"")
            probe.unlink()
            _resolved = d
            return d
        except OSError:
            continue
    _resolved = _candidates()[-1]
    return _resolved


def log_path() -> Path:
    return log_dir() / "export.log"


def _app_version() -> str:
    try:
        from .. import __version__           # noqa: PLC0415  app/__init__.py 里的版本号
        return str(__version__)
    except Exception:                       # noqa: BLE001
        return ""


def _write(record: dict[str, Any]) -> None:
    """追加一条。任何异常都吞掉：日志不能反过来搞坏导出。"""
    global _failed
    if _failed:
        return
    try:
        record.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S")
                          + (".%03d" % (int(time.time() * 1000) % 1000)))
        record.setdefault("app", _app_version())
        record.setdefault("pid", os.getpid())
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _LOCK:
            with open(log_path(), "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
    except Exception:                       # noqa: BLE001
        _failed = True                      # 一次失败就别反复试了
        if os.environ.get("M4S_LOG_DEBUG"):
            traceback.print_exc(file=sys.stderr)


def log_job(**fields: Any) -> None:
    """整个导出任务一条：开始与结束各写一次，便于把切片串起来。"""
    _write({"event": "job", **fields})


def log_slice(**fields: Any) -> None:
    """单个切片一条：切点、命令、耗时、结果。"""
    _write({"event": "slice", **fields})


def log_error(where: str, exc: BaseException | str, **fields: Any) -> None:
    text = exc if isinstance(exc, str) else "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__))
    _write({"event": "error", "where": where, "detail": text[-4000:], **fields})
