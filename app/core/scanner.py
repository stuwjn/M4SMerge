"""Steam 剪辑（clips）扫描。

只认 Steam「保存的剪辑」，不碰后台录制的整局回放：

    <Steam>\\userdata\\<好友码>\\gamerecordings\\clips\\
        clip_<appid>_<日期>_<时间>\\        ← 一条剪辑
            clip.pb                         （Steam 自己的元数据，本程序不解析）
            thumbnail.jpg                   ← 现成封面，不用抽帧
            timelines\\timeline_*.json
            video\\
                fg_<appid>_<日期>_<时间>\\  （或 bg_）
                    session.mpd
                    init-stream0.m4s
                    chunk-stream0-00001.m4s
                    …
                    init-stream1.m4s
                    chunk-stream1-00001.m4s
                    …

扫描只做三件事：定位分片目录、读清单拿轨道与时长、记下封面路径。
不解码、不抽帧、不动分片，所以几百条剪辑也是秒级。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .ffmpeg import FFmpeg
from .mpd import DashTrack, parse_mpd
from .naming import natural_key
from .recording import Recording, make_key

M4S_EXT = {".m4s", ".mp4", ".m4v"}     # 分片可能被误命名为 mp4
STREAM_ID_RE = re.compile(r"(?:stream|track|rep|video|audio|chunk-stream|dash)[-_ ]?(\d+)", re.I)
NUM_RE = re.compile(r"(\d+)")
CLIP_NAME_RE = re.compile(r"^clip[_-](\d+)", re.I)
THUMB_NAMES = ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png", "thumb.jpg")


@dataclass(frozen=True)
class Unmatched:
    """放着 m4s 却认不出来的目录。

    扫描会跳过它，界面据此提示用户「按 Steam 的形状改名」——识别逻辑不动，
    只是把「差在哪」说出来，省得用户对着一个空列表猜。
    """

    folder: Path
    m4s: int
    sample: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------- Steam 探测 ----------------
def _win_steam_path_from_registry() -> list[Path]:
    out: list[Path] = []
    if os.name != "nt":
        return out
    try:
        import winreg  # type: ignore
    except ImportError:
        return out
    targets = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, sub, key in targets:
        try:
            with winreg.OpenKey(hive, sub) as k:
                val, _ = winreg.QueryValueEx(k, key)
                if val:
                    out.append(Path(str(val).replace("/", "\\")))
        except OSError:
            continue
    return out


def find_steam_roots() -> list[Path]:
    cands = _win_steam_path_from_registry()
    if os.name == "nt":
        cands += [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
            Path(r"D:\Steam"),
            Path(r"E:\Steam"),
            Path(r"F:\Steam"),
            Path(os.path.expandvars(r"%ProgramFiles(x86)%\Steam")),
        ]
    seen: set[str] = set()
    roots: list[Path] = []
    for c in cands:
        try:
            if c and c.is_dir():
                k = str(c.resolve()).lower()
                if k not in seen:
                    seen.add(k)
                    roots.append(c.resolve())
        except OSError:
            continue
    return roots


def _steam_custom_clip_dir(steam: Path) -> list[Path]:
    """从 localconfig.vdf 里挖出用户自定义的录制保存目录（尽力而为）。

    Steam 允许把录制目录改到别的盘；改了之后 clips 也跟着走，
    这里把候选目录当作「上一层」，稍后由 _clip_dirs 继续往下找 clips。
    """
    out: list[Path] = []
    for cfg in steam.glob("userdata/*/config/localconfig.vdf"):
        try:
            text = cfg.read_text("utf-8", "ignore")
        except OSError:
            continue
        for m in re.finditer(r'"(?:video|clip|record|recording)[\w]*"\s+"([A-Za-z]:\\\\?[^"]{3,})"',
                             text, re.I):
            raw = m.group(1).replace("\\\\", "\\")
            p = Path(raw)
            if p.is_dir():
                out.append(p)
    return out


def steam_clip_dirs() -> list[Path]:
    """Steam 所有账号下的 clips 目录。"""
    dirs: list[Path] = []
    for steam in find_steam_roots():
        for p in steam.glob("userdata/*/gamerecordings/clips"):
            if p.is_dir():
                dirs.append(p)
        dirs.extend(_steam_custom_clip_dir(steam))
    seen: set[str] = set()
    uniq: list[Path] = []
    for d in dirs:
        try:
            k = str(d.resolve()).lower()
        except OSError:
            continue
        if k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq


def default_scan_roots(extra: Iterable[str] = ()) -> list[Path]:
    """自动扫描只认 Steam 的 clips；用户手动指定的目录才额外纳入。"""
    roots: list[Path] = []
    roots.extend(steam_clip_dirs())
    for s in extra:
        p = Path(os.path.expandvars(os.path.expanduser(str(s).strip().strip('"'))))
        if p.is_dir():
            roots.append(p)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        try:
            k = str(r.resolve()).lower()
        except OSError:
            continue
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ---------------- 目录解析 ----------------
def _num_key(p: Path) -> tuple:
    nums = NUM_RE.findall(p.stem)
    return (int(nums[-1]) if nums else 0, p.name)


def _stream_id(name: str) -> int | None:
    m = STREAM_ID_RE.search(name)
    return int(m.group(1)) if m else None


def _is_m4s(p: Path) -> bool:
    return p.suffix.lower() in M4S_EXT


def _thumb_for(clip_dir: Path) -> Path | None:
    for name in THUMB_NAMES:
        p = clip_dir / name
        if p.is_file():
            return p
    return None


def _appid_of(name: str) -> str:
    m = CLIP_NAME_RE.match(name)
    return m.group(1) if m else ""


def looks_like_clip(d: Path) -> bool:
    """判断一个目录是不是「一条剪辑」。

    Steam 的剪辑一定有 video/ 子目录或 clip.pb；也兼容用户手工整理的
    只含 m4s 的目录，避免「自己拷出来的一份」扫不到。
    """
    try:
        if (d / "video").is_dir() or (d / "clip.pb").is_file():
            return True
        if any((d / n).is_file() for n in THUMB_NAMES):
            return True
        with os.scandir(d) as it:
            for e in it:
                if e.is_file() and os.path.splitext(e.name)[1].lower() in M4S_EXT:
                    return True
    except OSError:
        return False
    return False


def clip_dirs_under(root: Path) -> list[Path]:
    """把一个扫描根展开成若干剪辑目录。

    兼容三种选法：直接选 clips、选到 gamerecordings、或者选到某一条剪辑。
    """
    root = Path(root)
    if looks_like_clip(root):
        return [root]
    # 选到 gamerecordings（上一级）时自动下钻到 clips
    sub = root / "clips"
    if sub.is_dir():
        root = sub
    out: list[Path] = []
    try:
        with os.scandir(root) as it:
            for e in it:
                if not e.is_dir():
                    continue
                p = Path(e.path)
                if looks_like_clip(p):
                    out.append(p)
    except OSError:
        return []
    return out


def _track_ok(t: DashTrack) -> bool:
    if not t.segments:
        return False
    if not any(s.exists() for s in t.segments):
        return False
    if t.init is not None and not t.init.exists():
        return False
    return True


def _tracks_from_filenames(m4s: list[Path]) -> list[DashTrack]:
    """没有清单时按 Steam 的命名约定（init-streamN / chunk-streamN-00001）分组。"""
    inits = [p for p in m4s if re.match(r"^(init|header|moov)", p.name, re.I)]
    segs = [p for p in m4s if p not in inits]
    if not segs:
        return []
    segs.sort(key=_num_key)

    if inits:
        groups: dict[int | None, list[Path]] = {}
        for s in segs:
            groups.setdefault(_stream_id(s.name), []).append(s)
        if len(groups) == 1 and None in groups and len(inits) == 1:
            return [DashTrack(kind="video", init=inits[0], segments=groups[None])]
        tracks: list[DashTrack] = []
        for init in inits:
            tid = _stream_id(init.name)
            track_segs = groups.get(tid) or []
            if not track_segs and len(inits) == 1:
                track_segs = segs
            if not track_segs:
                continue
            tracks.append(DashTrack(kind=_kind_of_init(init), init=init,
                                    segments=track_segs))
        if tracks:
            return tracks
    return [DashTrack(kind="video", init=None, segments=segs)]


def _kind_of_init(init: Path) -> str:
    """init 分片里 hdlr 写着 vide/soun，读几个字节就能定性，比 ffprobe 快两个数量级。"""
    from .mp4box import sniff_media_kind
    return sniff_media_kind(init) or "video"


def _content_dir(clip_dir: Path) -> Path | None:
    """剪辑里真正放 m4s 的那层：video/<fg|bg_...>/，或剪辑目录本身。"""
    video = clip_dir / "video"
    if video.is_dir():
        try:
            with os.scandir(video) as it:
                subs = [Path(e.path) for e in it if e.is_dir()]
        except OSError:
            subs = []
        # 优先挑真含分片的子目录；没有就退回第一个
        for p in subs:
            try:
                if any(f.suffix.lower() == ".m4s" for f in p.iterdir() if f.is_file()):
                    return p
            except OSError:
                continue
        if subs:
            return subs[0]
        if any(f.suffix.lower() == ".m4s" for f in video.iterdir() if f.is_file()):
            return video
    if any(f.suffix.lower() == ".m4s" for f in clip_dir.iterdir() if f.is_file()):
        return clip_dir
    return None


def _estimate_duration(tracks: list[DashTrack]) -> float:
    """清单没写时长时的估算：Steam 固定 3 秒一片，够列表显示用了。"""
    segs = max((len(t.segments) for t in tracks), default=0)
    return float(segs * 3) if segs else 0.0


def dirs_with_m4s(root: Path, max_depth: int = 4) -> list[Path]:
    """扫描根下所有「直接含有 m4s」的目录，限深。只读，不改任何东西。"""
    out: list[Path] = []
    stack: list[tuple[Path, int]] = [(Path(root), 0)]
    while stack:
        d, depth = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        if any(e.is_file() and os.path.splitext(e.name)[1].lower() in M4S_EXT
               for e in entries):
            out.append(d)
        if depth < max_depth:
            stack.extend((Path(e.path), depth + 1) for e in entries if e.is_dir())
    return out


def _why_unmatched(files: list[str], depth: int) -> str:
    """说清「差在哪」，别让用户对着空列表猜。"""
    if not files:
        return "目录里没有分片"
    if depth >= 3:
        return "分片层得太深：只往下看两层（剪辑文件夹 → video\\<一层>\\）"
    if not any(re.match(r"^(init|header|moov)", f, re.I) for f in files):
        return "缺 init 初始化段，分不出哪几片属于同一轨"
    if not any(re.search(r"\d", f) for f in files):
        return "文件名里没有序号，排不出播放顺序"
    return "文件名或层级不符合 Steam 的约定"


def analyze_clip(clip_dir: Path, ff: FFmpeg) -> Recording | None:
    """解析一条剪辑。返回 None 表示这里没有可合并的分片。"""
    content = _content_dir(clip_dir)
    if content is None:
        return None

    tracks: list[DashTrack] = []
    mpd: Path | None = None
    for candidate in sorted(content.glob("*.mpd")):
        parsed = [t for t in parse_mpd(candidate) if _track_ok(t)]
        if parsed:
            tracks, mpd = parsed, candidate
            break
    if not tracks:
        try:
            m4s = [f for f in content.iterdir() if f.is_file() and f.suffix.lower() in M4S_EXT]
        except OSError:
            return None
        tracks = [t for t in _tracks_from_filenames(m4s) if _track_ok(t)]
    if not tracks:
        return None

    size = 0
    mtime = 0.0
    files: list[Path] = []
    for t in tracks:
        if t.init:
            files.append(t.init)
        files.extend(t.segments)
    for f in files:
        try:
            st = f.stat()
            size += st.st_size
            mtime = max(mtime, st.st_mtime)
        except OSError:
            continue
    if mtime == 0.0:
        try:
            mtime = clip_dir.stat().st_mtime
        except OSError:
            pass

    declared = max((t.duration for t in tracks), default=0.0) or _estimate_duration(tracks)
    warnings: list[str] = []
    if len(tracks) < 2:
        warnings.append("只有单轨，导出可能没有声音")

    # 重命名用的时间戳以封面为准：Steam 写 thumbnail.jpg 的那一刻就是剪辑生成时刻
    thumb = _thumb_for(clip_dir)
    stamp = 0.0
    if thumb is not None:
        try:
            stamp = thumb.stat().st_mtime
        except OSError:
            stamp = 0.0

    return Recording(
        key=make_key(clip_dir),
        path=clip_dir,
        kind="dash",
        title=clip_dir.name,
        mtime=mtime,
        size=size,
        tracks=tracks,
        mpd=mpd,
        warnings=warnings,
        declared_duration=declared,
        thumb=thumb,
        appid=_appid_of(clip_dir.name),
        stamp=stamp,
    )


class Scanner:
    def __init__(self, ff: FFmpeg, max_depth: int = 4) -> None:
        self.ff = ff
        self.max_depth = max_depth

    def scan(self, roots: Iterable[Path],
             on_progress: Callable[[str, int], None] | None = None) -> list[Recording]:
        return self.scan_ex(roots, on_progress)[0]

    def scan_ex(self, roots: Iterable[Path],
                on_progress: Callable[[str, int], None] | None = None
                ) -> tuple[list[Recording], list[Unmatched]]:
        """返回（认出来的剪辑, 放着 m4s 但认不出的目录）。

        第二项只用来提示用户改名，不参与识别、不影响第一项。
        """
        roots = [Path(r) for r in roots]
        found: list[Recording] = []
        claimed: set[str] = set()          # 已经认领的分片目录，回头从「认不出」里排掉
        seen: set[str] = set()
        for root in roots:
            for clip_dir in clip_dirs_under(root):
                try:
                    k = str(clip_dir.resolve()).lower()
                except OSError:
                    continue
                if k in seen:
                    continue
                seen.add(k)
                if on_progress:
                    on_progress(str(clip_dir), len(found))
                try:
                    rec = analyze_clip(clip_dir, self.ff)
                except OSError:
                    rec = None
                if rec is not None:
                    found.append(rec)
                    content = _content_dir(clip_dir)
                    if content is not None:
                        try:
                            claimed.add(str(content.resolve()).lower())
                        except OSError:
                            pass
        found.sort(key=lambda r: r.mtime, reverse=True)
        return found, self._unmatched(roots, claimed)

    def _unmatched(self, roots: list[Path], claimed: set[str]) -> list[Unmatched]:
        out: list[Unmatched] = []
        seen: set[str] = set()
        for root in roots:
            for d in dirs_with_m4s(root, self.max_depth):
                try:
                    key = str(d.resolve()).lower()
                except OSError:
                    continue
                if key in claimed or key in seen:
                    continue
                seen.add(key)
                try:
                    names = [p.name for p in d.iterdir()
                             if p.is_file() and p.suffix.lower() in M4S_EXT]
                except OSError:
                    continue
                names.sort(key=natural_key)
                try:
                    depth = len(d.relative_to(root).parts)
                except ValueError:
                    depth = 1
                out.append(Unmatched(folder=d, m4s=len(names), sample=names[:4],
                                     reason=_why_unmatched(names, depth)))
        return out


def build_recording_for_dir(path: Path, ff: FFmpeg) -> Recording | None:
    """用户手动选了一条剪辑目录时使用。"""
    p = Path(path)
    if not p.is_dir():
        return None
    return analyze_clip(p, ff)
