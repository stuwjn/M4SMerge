"""剪辑文件模型 + 合并流水线。

核心思路：Steam 剪辑目录里是一串 DASH 分片（fMP4）。同一轨的分片按
init → seg1..segN 顺序做字节拼接，天然就是合法的 fragmented MP4，
**无需解码**；之后 `-c copy` 封装成普通 mp4，音视频轨分别还原后一次
mux，全程零转码（真正无损），速度约等于磁盘拷贝。

M4SMerge 只做这一件事：把这个目录合成为一个 mp4 文件。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .ffmpeg import FFmpeg, FFmpegError, MediaInfo
from .mpd import DashTrack
from .settings import APP_NAME, app_temp_dir
from .utils import fmt_mtime, human_duration, human_size

ProgressFn = Callable[[float, str], None]

# 本进程内所有已还原的临时文件。Preparer 可能被重建/丢弃，靠这个集合兜底清理。
_LIVE_FILES: set[Path] = set()


class Canceled(Exception):
    """用户主动取消（与真正失败区分：取消不弹错误框）。"""


@dataclass
class Recording:
    """一条 Steam 剪辑。

    `path` 是剪辑自己的文件夹（clip_<appid>_<日期>_<时间>），
    `tracks` 指向它 video/<fg|bg>_.../ 下面的分片。
    """
    key: str
    path: Path
    kind: str                                  # "dash" | "file"
    title: str = ""
    mtime: float = 0.0
    size: int = 0
    tracks: list[DashTrack] = field(default_factory=list)
    mpd: Path | None = None
    warnings: list[str] = field(default_factory=list)
    declared_duration: float = 0.0
    prepared: Path | None = None               # 合并后的 mp4（仅导出流程内部用）
    info: MediaInfo | None = None
    thumb: Path | None = None                  # thumbnail.jpg（Steam 现成的封面）
    appid: str = ""                            # 目录名里的 Steam AppID

    @property
    def duration(self) -> float:
        if self.info and self.info.duration:
            return self.info.duration
        return self.declared_duration

    @property
    def is_ready(self) -> bool:
        """有分片就能合并，不需要事先建索引、也不需要落地完整 mp4。"""
        return bool(self.tracks)

    # ---------- 展示 ----------
    @property
    def subtitle(self) -> str:
        bits = [human_size(self.size), fmt_mtime(self.mtime)]
        if self.duration:
            bits.insert(0, human_duration(self.duration))
        if self.info and self.info.resolution:
            bits.append(self.info.resolution)
        return "  ·  ".join(b for b in bits if b)

    # ---------- 源文件 ----------
    def source_files(self) -> list[Path]:
        if self.kind == "file":
            return [self.path]
        out: list[Path] = []
        for t in self.tracks:
            if t.init:
                out.append(t.init)
            out.extend(t.segments)
        return out


def make_key(path: Path) -> str:
    return hashlib.blake2b(str(path).encode("utf-8", "replace"), digest_size=8).hexdigest()


class Preparer:
    """把一条剪辑（m4s 分片集合 / 单个 mp4）合成一个 mp4。

    **不写系统盘、不留长期缓存**：
    · 中间片落在「程序目录下的 temp」，游戏目录、剪辑目录一概不碰。
    · 用完即删：导出结束 / 关闭程序时清空，正常退出不留任何中间文件。
    · 正在被导出队列引用的文件会被 pin 住，任务结束才删。
    """

    def __init__(self, ff: FFmpeg, temp_dir: str = "") -> None:
        self.ff = ff
        self._temp_dir = (temp_dir or "").strip()
        self._live: dict[str, Path] = {}     # rec.key -> 已还原好的 mp4
        self._pinned: set[str] = set()       # 正被队列使用的路径（不删）

    def reconfigure(self, ff: FFmpeg, temp_dir: str = "") -> None:
        """设置变更后原地更新（不重建对象，否则 _live 里的临时文件会失去跟踪）。"""
        self.ff = ff
        self._temp_dir = (temp_dir or "").strip()

    # ---------- 临时目录 ----------
    def _candidates(self, rec: Recording) -> list[Path]:
        """候选临时根目录，按优先级排列。

        绝不回落到剪辑目录（gamerecordings 应该只有原始分片和用户自己的成品）。
        """
        out: list[Path] = []
        if self._temp_dir:
            out.append(Path(self._temp_dir))
        out.append(app_temp_dir())
        out.append(Path(tempfile.gettempdir()) / APP_NAME)
        return out

    def _is_own_dir(self, d: Path) -> bool:
        """程序自己的 temp 可以整个删；用户指定的目录只清空文件、保留文件夹。"""
        own = {app_temp_dir(), Path(tempfile.gettempdir()) / APP_NAME}
        try:
            target = os.path.normcase(str(d.resolve()))
            return any(os.path.normcase(str(p.resolve())) == target for p in own)
        except OSError:
            return False

    def work_dir(self, rec: Recording) -> Path:
        """选一个真正可写的临时目录。程序目录优先，全部失败才退系统临时目录。"""
        last: Exception | None = None
        for d in self._candidates(rec):
            try:
                d.mkdir(parents=True, exist_ok=True)
                probe = d / f".w{uuid.uuid4().hex[:6]}"
                probe.write_bytes(b"")
                probe.unlink()
                return d
            except OSError as exc:
                last = exc
        raise FFmpegError(f"没有可写的临时目录：{last}")

    # ---------- 对外 ----------
    def prepare(self, rec: Recording, progress: ProgressFn | None = None,
                cancel: threading.Event | None = None) -> MediaInfo:
        def report(p: float, msg: str) -> None:
            if progress:
                progress(max(0.0, min(1.0, p)), msg)

        # 已是普通 mp4/m4a：直接使用，零拷贝、零临时文件
        if rec.kind == "file" and rec.path.suffix.lower() in (".mp4", ".mov", ".m4v", ".m4a"):
            info = self.ff.probe(rec.path)
            if info.has_video or info.has_audio:
                rec.prepared, rec.info = rec.path, info
                report(1.0, "已就绪")
                return info

        if cancel is not None and cancel.is_set():
            raise Canceled()
        if not rec.tracks:
            raise FFmpegError("没有解析到任何音视频轨，无法合并")

        root = self.work_dir(rec)
        self._sweep_stale(root)
        out = root / f"{rec.key}.mp4"

        # 本次会话里已经还原过、且比源文件新 → 直接复用
        if out.exists() and out.stat().st_size > 1024:
            try:
                fresh = out.stat().st_mtime >= rec.mtime
            except OSError:
                fresh = False
            if fresh:
                info = self.ff.probe(out)
                if info.has_video or info.has_audio:
                    rec.prepared, rec.info = out, info
                    self._live[rec.key] = out
                    _LIVE_FILES.add(out)
                    report(1.0, "已就绪")
                    return info

        # 目录名带唯一后缀：同一条剪辑被并发还原时，两个任务的临时目录互不相干。
        work = root / f".work_{rec.key}_{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            report(0.02, "准备分片…")
            parts: list[tuple[Path, MediaInfo]] = []
            track_total = max(1, len(rec.tracks))
            missing_total = 0
            for idx, tr in enumerate(rec.tracks):
                base = 0.05 + 0.65 * idx / track_total
                span = 0.65 / track_total

                def tp(p: float, b=base, s=span, k=tr.kind) -> None:
                    report(b + s * p, f"拼接 {k} 轨…")

                part = work / f"part_{idx}_{tr.kind or 'track'}.mp4"
                missing = self._concat_bytes(tr, part, tp, cancel)
                missing_total += missing
                if not part.exists():
                    raise FFmpegError(
                        f"{tr.kind or '未知'} 轨拼接结果丢失（临时目录被外部清理），请重试")
                if part.stat().st_size == 0:
                    rec.warnings.append(f"{tr.kind} 轨为空，已跳过")
                    continue
                pinfo = self.ff.probe(part)
                if not (pinfo.has_video or pinfo.has_audio):
                    rec.warnings.append(f"{tr.kind} 轨数据无法识别，已跳过")
                    continue
                parts.append((part, pinfo))

            if missing_total:
                # 录制中断/分片被清理时会出现，画面会跳帧，必须让用户知道
                rec.warnings.append(f"缺失 {missing_total} 个分片，画面可能不连续")

            if not parts:
                raise FFmpegError("所有轨道拼接后均无效（分片可能缺失或已损坏）")

            report(0.72, "封装 MP4…")
            # 先写 .part 再原子改名：中途取消或崩溃都不会留下「看着像个好文件」的半截结果
            part_out = root / f".{rec.key}.{uuid.uuid4().hex[:8]}.part"
            try:
                if part_out.exists():
                    part_out.unlink()
                self._mux(parts, part_out, cancel)
                info = self.ff.probe(part_out)
                if not (info.has_video or info.has_audio):
                    raise FFmpegError("封装失败：输出文件无有效流")
                os.replace(part_out, out)
            finally:
                if part_out.exists():
                    try:
                        part_out.unlink()
                    except OSError:
                        pass
            rec.prepared, rec.info = out, info
            self._live[rec.key] = out
            _LIVE_FILES.add(out)
            report(1.0, "就绪")
            return info
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ---------- 生命周期 ----------
    def pin(self, path: str | Path | None) -> None:
        if path:
            self._pinned.add(str(Path(path)))

    def unpin(self, path: str | Path | None) -> None:
        if path:
            self._pinned.discard(str(Path(path)))

    def release_path(self, path: str | Path | None) -> None:
        """按文件路径释放（导出队列用完一条就放一条）。"""
        if not path:
            return
        target = str(Path(path))
        for key, p in list(self._live.items()):
            if str(p) == target:
                self.release(key)
                return

    def release(self, key: str) -> None:
        """删掉某条剪辑的临时文件（被队列引用时跳过）。"""
        p = self._live.get(key)
        if p is None:
            return
        if str(p) in self._pinned:
            return          # 队列还在用：保留跟踪，任务结束再按路径释放
        self._live.pop(key, None)
        try:
            p.unlink()
        except OSError:
            return
        _LIVE_FILES.discard(p)
        self._trim(p.parent)

    def cleanup_all(self) -> int:
        """删掉全部临时文件（退出时调用）。返回删除的字节数。"""
        freed = 0
        roots: set[Path] = {app_temp_dir(), Path(tempfile.gettempdir()) / APP_NAME}
        if self._temp_dir:
            roots.add(Path(self._temp_dir))
        paths = set(_LIVE_FILES)
        paths.update(self._live.values())
        for p in paths:
            if not p.exists():
                _LIVE_FILES.discard(p)
                continue
            roots.add(p.parent)
            if str(p) in self._pinned:
                continue
            try:
                freed += p.stat().st_size
            except OSError:
                pass
            try:
                p.unlink()
                _LIVE_FILES.discard(p)
            except OSError:
                continue
        self._live.clear()
        # 上次异常退出（被杀进程/断电）可能留下 .work_* / 还原片，
        # 这些不在本次进程的登记表里，但同样要清——temp 是「退出即空」的。
        for d in roots:
            for p in list(d.glob("*.mp4")):
                if str(p) in self._pinned:
                    continue
                try:
                    freed += p.stat().st_size
                    p.unlink()
                except OSError:
                    pass
            for junk in list(d.glob("m4s-export-*")):
                shutil.rmtree(junk, ignore_errors=True)
            self._sweep_stale(d)
            self._trim(d)
        return freed

    def _trim(self, d: Path) -> None:
        """清掉空壳：程序自己的 temp 空了就删，用户指定的目录保留。"""
        try:
            for junk in d.glob(".part*"):
                junk.unlink(missing_ok=True)
            if any(d.iterdir()):
                return
            if self._is_own_dir(d):
                d.rmdir()
        except OSError:
            pass

    def _sweep_stale(self, root: Path, max_age: float = 600.0) -> None:
        """清掉上次异常退出（被杀进程/断电）留下的中间目录。"""
        now = time.time()
        for d in list(root.glob(".work_*")) + list(root.glob(".w_*")):
            try:
                if now - d.stat().st_mtime < max_age:
                    continue
            except OSError:
                continue
            shutil.rmtree(d, ignore_errors=True)

    # ---------- 内部 ----------
    def _concat_bytes(self, tr: DashTrack, dst: Path, on_progress, cancel) -> int:
        """把一轨的分片按字节拼成 fMP4。返回缺失的分片数。"""
        files: list[Path] = []
        if tr.init:
            files.append(tr.init)
        missing = 0
        for seg in tr.segments:
            if seg.exists():
                files.append(seg)
            else:
                missing += 1
        return missing + self._copy_into(files, dst, on_progress, cancel)

    def _copy_into(self, files: list[Path], dst: Path, on_progress,
                   cancel) -> int:
        """按字节把 files 依次写进 dst。返回读取失败的文件数。"""
        total = 0
        for f in files:
            try:
                total += f.stat().st_size
            except OSError:
                pass
        done = 0
        failed = 0
        buf = 8 * 1024 * 1024
        with open(dst, "wb") as w:
            for f in files:
                if cancel is not None and cancel.is_set():
                    raise Canceled()
                try:
                    with open(f, "rb") as r:
                        while True:
                            # 大分片单个就有几十 MB，循环内也要检查，否则取消要等一整片读完
                            if cancel is not None and cancel.is_set():
                                raise Canceled()
                            chunk = r.read(buf)
                            if not chunk:
                                break
                            w.write(chunk)
                            done += len(chunk)
                            if total:
                                on_progress(done / total)
                except OSError:
                    failed += 1   # 读失败按缺失处理，最终汇总进 warnings
                    continue
        return failed

    def _mux(self, parts: list[tuple[Path, MediaInfo]], out: Path,
             cancel: threading.Event | None) -> None:
        """按**实际探测到的流**映射，而不是按「这条 part 是视频还是音频」。

        旧写法给每个 part 贴一个 video/audio 标签再各取一个，一旦某条 part
        同时带音视频（或被误判），就会整条轨丢掉——表现就是「导出只有画面」
        或「只有声音」。这里改成：视频取第一个真的含视频流的输入，
        音频取第一个真的含音频流的输入，两者相同时只导入一次。
        """
        video_path = next((p for p, info in parts if info.has_video), None)
        audio_path = next((p for p, info in parts if info.has_audio), None)
        if video_path is None and audio_path is None:
            raise FFmpegError("无可封装轨道")

        inputs: list[Path] = []
        maps: list[str] = []
        if video_path is not None:
            inputs.append(video_path)
            maps += ["-map", "0:v:0"]
            if audio_path is not None:
                if audio_path == video_path:
                    maps += ["-map", "0:a:0"]
                else:
                    inputs.append(audio_path)
                    maps += ["-map", f"{len(inputs) - 1}:a:0"]
        else:
            inputs.append(audio_path)      # type: ignore[arg-type]
            maps += ["-map", "0:a:0"]

        args: list[str] = []
        for p in inputs:
            args += ["-i", str(p)]
        args += maps
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero",
                 "-movflags", "+faststart", "-f", "mp4", str(out)]
        code, err = self.ff.run(args, cancel=cancel)
        if code == 130:
            raise Canceled()
        if code != 0:
            tail = "\n".join(err.splitlines()[-6:]) if err else f"退出码 {code}"
            raise FFmpegError(f"封装失败：{tail}")
