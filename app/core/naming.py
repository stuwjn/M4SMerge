"""Steam 剪辑的命名与摆法，以及「不合规的 m4s 目录」的整改建议。

扫描与分轨只认 Steam 的约定（见 scanner.py），这里**不参与识别**。
它只负责把「要改成什么样」讲清楚：规则、示例目录树、逐个文件的改名对照。
README、界面提示都引这一份，免得三处说法走样。

一条剪辑的目标形状：

    clips\\
    └─ my_clip\\                     ← 一个文件夹 = 一条剪辑，名字随便起
       ├─ thumbnail.jpg              ← 可选，有就当封面
       └─ video\\
          └─ fg_1\\                   ← 一层子目录，名字随便起
             ├─ init-stream0.m4s      ← 视频轨初始化段
             ├─ chunk-stream0-00001.m4s
             ├─ init-stream1.m4s      ← 音频轨初始化段
             └─ chunk-stream1-00001.m4s
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .utils import safe_filename

M4S_EXT = {".m4s", ".mp4", ".m4v"}
_NUM_RE = re.compile(r"(\d+)")
_INIT_RE = re.compile(r"(^|[^a-z])(init|header|moov)([^a-z]|$)", re.I)

#: 输出名里时间戳的格式。Windows 文件名不能带冒号，时分秒用短横线隔开：
#:     影之刃零 - 2026-11-22 23-46-00
STAMP_FMT = "%Y-%m-%d %H-%M-%S"

#: 名称与时间戳之间的分隔（前后各一个空格）
STAMP_JOIN = " - "

#: 一条剪辑的目标形状。逐行给出（树行, 注释），界面按两列渲染，
#: 纯文本场景再按显示宽度补空格，中文与框线字符宽度不同也不会错位。
TREE_ROWS: list[tuple[str, str]] = [
    ("clips\\", ""),
    ("└─ my_clip\\", "一个文件夹 = 一条剪辑，名字随便起"),
    ("   ├─ thumbnail.jpg", "可选，有就拿来当封面"),
    ("   └─ video\\", ""),
    ("      └─ fg_1\\", "一层子目录，名字随便起"),
    ("         ├─ init-stream0.m4s", "视频轨的初始化段"),
    ("         ├─ chunk-stream0-00001.m4s", ""),
    ("         ├─ chunk-stream0-00002.m4s", ""),
    ("         ├─ init-stream1.m4s", "音频轨的初始化段"),
    ("         └─ chunk-stream1-00001.m4s", ""),
]


def _disp_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _tree_text() -> str:
    col = max(_disp_width(a) for a, _ in TREE_ROWS) + 2
    out = []
    for path, note in TREE_ROWS:
        out.append(path + " " * max(1, col - _disp_width(path)) + note if note else path)
    return "\n".join(out)


#: 同上，等宽字体下注释能对齐的纯文本版
TARGET_TREE = _tree_text()

#: 改名要点：(规则, 说明)
RULES: list[tuple[str, str]] = [
    ("一个文件夹 = 一条剪辑", "放在 clips\\ 下，或你手动指定的扫描根下"),
    ("名字里的 N 是轨号", "同一轨的 init 与 chunk 用同一个 N；画面用 0、声音用 1 最省事"),
    ("末尾数字是播放顺序", "可以跳号，但必须能排出先后"),
]

#: 一句话结论，界面与文档共用
ONE_LINER = "文件名和目录层级照 Steam 的样子摆好，不用改任何设置，重新扫描就能认出来。"

#: 手动重命名的边界：只动输出名，不碰剪辑目录
RENAME_HINT = "只改输出的文件名，剪辑目录一个字节都不动。"


def stamp_text(ts: float) -> str:
    """把时间戳变成 `2026-11-22 23-46-00`；时间越界时返回空串。"""
    try:
        return datetime.fromtimestamp(ts).strftime(STAMP_FMT)
    except (OSError, ValueError, OverflowError):
        return ""


def compose_out_name(base: str, ts: float, with_stamp: bool, maxlen: int = 100) -> str:
    """名称 + 可选时间戳 → 可直接当文件名的主干（不含扩展名）。

    先按剩余长度截名称、再拼时间戳：时间戳是这条名字的唯一标识，
    不能被一刀切掉。
    """
    base = safe_filename((base or "").strip(), maxlen)
    if not with_stamp:
        return base
    stamp = stamp_text(ts)
    if not stamp:
        return base
    room = max(8, maxlen - len(STAMP_JOIN) - len(stamp))
    return f"{safe_filename(base, room)}{STAMP_JOIN}{stamp}"


def rec_stamp(rec) -> float:
    """这条剪辑打时间戳用的时间。

    优先 `Recording.stamp_time`（thumbnail.jpg 的文件时间），
    没有就退回 `mtime`——测试夹具、单文件素材都可能没有封面。
    """
    ts = getattr(rec, "stamp_time", None)
    if isinstance(ts, (int, float)) and ts > 0:
        return float(ts)
    return float(getattr(rec, "mtime", 0.0) or 0.0)


def plan_out_names(recs: Iterable, base: str, with_stamp: bool,
                   maxlen: int = 100) -> dict[str, str]:
    """一批剪辑的输出名：名称共用，时间各用各的，撞名自动补 -2。

    返回 {rec.key: 名字}。对话框的预览和真正的导出都走这里，
    免得「预览一个样、导出来另一个样」。
    """
    out: dict[str, str] = {}
    used: set[str] = set()
    for rec in sorted(recs, key=lambda r: (rec_stamp(r), getattr(r, "title", ""))):
        name = compose_out_name(base, rec_stamp(rec), with_stamp, maxlen)
        if name in used:
            for i in range(2, 1000):
                cand = f"{name}-{i}"
                if cand not in used:
                    name = cand
                    break
        used.add(name)
        out[getattr(rec, "key", name)] = name
    return out


def natural_key(name: str) -> tuple:
    """把 00010 排在 0009 后面的排序键。"""
    parts = []
    for tok in _NUM_RE.split(name):
        if not tok:
            continue
        parts.append((0, int(tok)) if tok.isdigit() else (1, tok.lower()))
    return tuple(parts)


def is_init(name: str) -> bool:
    return bool(_INIT_RE.search(Path(name).stem))


@dataclass
class RenamePlan:
    """一个认不出的目录该怎么改：逐文件对照 + 一句提醒。"""

    folder: Path
    rows: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""

    @property
    def count(self) -> int:
        return len(self.rows)


def _m4s_files(directory: Path) -> list[Path]:
    try:
        files = [p for p in directory.iterdir()
                 if p.is_file() and p.suffix.lower() in M4S_EXT]
    except OSError:
        return []
    files.sort(key=lambda p: natural_key(p.name))
    return files


def plan_renames(directory: Path, limit: int = 8) -> RenamePlan | None:
    """给一个目录生成改名建议。

    只处理「一条轨」的情形（0 个或 1 个初始化段）——这是绝大多数；
    出现多个 init 说明本来就有多条轨，此时不给逐条对照，让用户按规则自己分，
    免得猜错轨号把音画对错。
    """
    directory = Path(directory)
    files = _m4s_files(directory)
    if not files:
        return None

    inits = [p for p in files if is_init(p.name)]
    segs = [p for p in files if p not in inits]

    if len(inits) > 1:
        return RenamePlan(
            folder=directory,
            rows=[],
            note=("这里有 %d 个初始化段，说明本来就有两条轨以上。"
                  "请把属于画面的分片与属于声音的分片各放一组："
                  "画面那组的 init 与 chunk 都用 stream0，声音那组都用 stream1。"
                  % len(inits)),
        )

    rows: list[tuple[str, str]] = []
    if inits:
        rows.append((inits[0].name, "init-stream0.m4s"))
    for i, p in enumerate(segs, 1):
        rows.append((p.name, "chunk-stream0-%05d.m4s" % i))
    if len(rows) > limit:
        head, tail = rows[:limit - 2], rows[-1]
        more = len(rows) - (limit - 1)
        rows = head + [("……", "其余 %d 个同样按顺序编号" % more)] + [tail]

    note = ("如果这批文件里既有画面又有声音，先分成两堆：画面那堆照上面用 stream0，"
            "声音那堆用 stream1，编号各自从 00001 开始。")
    return RenamePlan(folder=directory, rows=rows, note=note)


def plan_for(folders: Iterable[Path], max_plans: int = 6) -> list[RenamePlan]:
    out: list[RenamePlan] = []
    for f in list(folders)[:max_plans]:
        p = plan_renames(f)
        if p is not None:
            out.append(p)
    return out


def clipboard_text(plans: list[RenamePlan] | None = None) -> str:
    """「复制做法」按钮写进剪贴板的内容：规则 + 示例树 + 现有对照。"""
    lines = ["M4SMerge 认得的摆法（照着改，不用改任何设置）：", "", TARGET_TREE, "", "要点："]
    lines += ["- %s：%s" % (a, b) for a, b in RULES]
    for plan in plans or []:
        if not plan.rows:
            continue
        lines += ["", "【%s】" % plan.folder, "现在的名字 → 改成"]
        lines += ["  %s → %s" % (a, b) for a, b in plan.rows]
        if plan.note:
            lines.append("  注：" + plan.note)
    return "\n".join(lines)
