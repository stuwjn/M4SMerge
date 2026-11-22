"""小工具函数：格式化、时间码、文件名清洗。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = float(seconds)
    h, rem = divmod(int(round(seconds)), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def human_ts(seconds: float) -> str:
    """用于文件名的短时间戳，如 75.32 -> 75.3"""
    return f"{max(0.0, seconds):.1f}"


def safe_filename(name: str, maxlen: int = 120) -> str:
    name = _INVALID.sub("_", name).strip().strip(".")
    return (name or "clip")[:maxlen]


def fmt_mtime(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return ""


def ensure_unique(path: Path, taken: set[Path] | None = None) -> Path:
    """不覆盖已有文件：重名时依次追加 -2、-3……

    以前用「名字 (1).mp4」，括号在批处理脚本和部分播放器里要转义；
    短横线更省事，也符合常见下载工具的命名习惯。

    `taken` 是本批次已经**预占**的路径：批量导出时文件还没落盘，
    只查 exists() 会让两条同名剪辑抢同一个文件名。
    """
    taken = taken or set()
    if not path.exists() and path not in taken:
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(2, 1000):
        cand = parent / f"{stem}-{i}{suffix}"
        if not cand.exists() and cand not in taken:
            return cand
    return parent / f"{stem}_{id(path)}{suffix}"
