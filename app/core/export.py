"""导出：把一条剪辑合成一个 mp4。

M4SMerge 不做剪切，所以这里只有「整条直通」一条路：

    ffmpeg -i <已合并的 fMP4> -map 0:v:0? -map 0:a:0? -c copy -movflags +faststart out.mp4

直通失败（分片编码不规整、时间戳跳变等）时才降级为重编码，
保证用户不会拿到一个 0 字节的结果。
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from . import oplog
from .ffmpeg import FFmpeg, FFmpegError
from .settings import APP_NAME, app_temp_dir
from .utils import ensure_unique

if TYPE_CHECKING:                       # 只为标注，不在运行时引入循环依赖
    from .recording import Recording


@dataclass
class ExportJob:
    src: "Path | str"            # 已合并好的 mp4（Preparer 产出）
    out: Path
    title: str = ""
    duration: float = 0.0
    compress: bool = False       # False=无损直通（默认）；True=重编码压到 1080p
    status: str = "pending"      # pending | running | done | failed | canceled
    progress: float = 0.0
    message: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    results: list[Path] = field(default_factory=list)
    # 供日志用：分片数 / 源体积 / 缺失片数，出问题时能对上号
    segments: int = 0
    src_size: int = 0
    missing: int = 0
    rec: "Recording | None" = None       # 来源剪辑（队列里先拼接再封装）


class Exporter:
    def __init__(self, ff: FFmpeg, temp_dir: str = "") -> None:
        self.ff = ff
        self._temp_dir = (temp_dir or "").strip()
        self._encoders: set[str] | None = None

    def _make_tmp(self, out: Path) -> Path:
        """中间片放程序 temp，不污染用户的输出目录。"""
        roots: list[Path] = []
        if self._temp_dir:
            roots.append(Path(self._temp_dir))
        roots += [app_temp_dir(), Path(tempfile.gettempdir()) / APP_NAME]
        for root in roots:
            try:
                root.mkdir(parents=True, exist_ok=True)
                return Path(tempfile.mkdtemp(prefix="m4s-export-", dir=str(root)))
            except OSError:
                continue
        fallback = out.parent / f".tmp_{out.stem}"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def encoders(self) -> set[str]:
        if self._encoders is None:
            self._encoders = self.ff.encoders()
        return self._encoders

    def pick_video_encoder(self) -> str:
        enc = self.encoders()
        for cand in ("libx264", "libopenh264", "h264_nvenc", "h264_qsv", "h264_amf", "mpeg4"):
            if cand in enc:
                return cand
        return "libx264"

    # ---------- 命令构造 ----------
    def _cmd_copy(self, src: "Path | str", out: Path) -> list[str]:
        return ["-i", str(src),
                "-map", "0:v:0?", "-map", "0:a:0?",
                "-c", "copy", "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart", "-f", "mp4", str(out)]

    def _cmd_reencode(self, src: "Path | str", out: Path) -> list[str]:
        venc = self.pick_video_encoder()
        args = ["-i", str(src), "-map", "0:v:0?", "-map", "0:a:0?",
                "-c:v", venc, "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p"]
        if venc == "mpeg4":
            args += ["-q:v", "3"]
        args += ["-vf", "scale='if(gt(iw,1920),1920,iw)':-2"]
        args += ["-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", "-f", "mp4", str(out)]
        return args

    # ---------- 执行 ----------
    def run_job(self, job: ExportJob,
                on_progress: Callable[[float, str], None] | None = None) -> ExportJob:
        def report(p: float, msg: str) -> None:
            job.progress = max(0.0, min(1.0, p))
            job.message = msg
            if on_progress:
                on_progress(job.progress, msg)

        if not Path(job.src).exists():
            job.status, job.message = "failed", "源文件已被清理，请重新导出"
            oplog.log_error("run_job", job.message, title=job.title, out=str(job.out))
            return job

        job.status = "running"
        job.results = []
        t_start = time.time()
        oplog.log_job(status="start", title=job.title, out=str(job.out),
                      src=str(job.src), duration=round(job.duration, 3),
                      compress=job.compress, segments=job.segments,
                      src_size=job.src_size, missing=job.missing,
                      ffmpeg=self.ff.ffmpeg)

        try:
            job.out.parent.mkdir(parents=True, exist_ok=True)
            # 输出先写 .part 再改名：中途取消/断电不会留下「看着像成品」的半截文件
            tmp_out = job.out.with_name(f".{job.out.stem}.{int(time.time())}.part")
            try:
                degraded = False
                args = (self._cmd_reencode if job.compress else self._cmd_copy)(job.src, tmp_out)
                t0 = time.time()
                code, err = self.ff.run(args, duration=job.duration or None,
                                        on_progress=lambda p: report(p, "合并中"),
                                        cancel=job.cancel)
                elapsed = int((time.time() - t0) * 1000)
                if code == 130:
                    raise _Canceled
                if code != 0 and not job.compress:
                    # 直通失败 → 重编码兜底，保证有产物
                    first_error = self._tail(err, code)
                    args2 = self._cmd_reencode(job.src, tmp_out)
                    t1 = time.time()
                    code2, err2 = self.ff.run(args2, duration=job.duration or None,
                                              on_progress=lambda p: report(p, "重编码中"),
                                              cancel=job.cancel)
                    elapsed = int((time.time() - t1) * 1000)
                    if code2 == 130:
                        raise _Canceled
                    oplog.log_slice(job=job.title, out=str(job.out), src=str(job.src),
                                    stage="reencode", mode="reencode",
                                    elapsed_ms=elapsed, status="ok" if code2 == 0 else "failed",
                                    degraded=True, first_code=code, first_error=first_error,
                                    cmd=" ".join([self.ff.ffmpeg, *args2]),
                                    error="" if code2 == 0 else self._tail(err2, code2))
                    if code2 != 0:
                        raise FFmpegError(self._tail(err2, code2))
                    degraded = True
                elif code != 0:
                    oplog.log_slice(job=job.title, out=str(job.out), src=str(job.src),
                                    stage="reencode", mode="reencode",
                                    elapsed_ms=elapsed, status="failed",
                                    cmd=" ".join([self.ff.ffmpeg, *args]),
                                    error=self._tail(err, code))
                    raise FFmpegError(self._tail(err, code))
                else:
                    oplog.log_slice(job=job.title, out=str(job.out), src=str(job.src),
                                    stage="mux", mode="reencode" if job.compress else "copy",
                                    elapsed_ms=elapsed, status="ok",
                                    cmd=" ".join([self.ff.ffmpeg, *args]))
                tmp_out.replace(job.out)
            finally:
                if tmp_out.exists():
                    try:
                        tmp_out.unlink()
                    except OSError:
                        pass

            job.results.append(job.out)
            report(1.0, "完成")
            job.status = "done"
            if degraded:
                job.message = "完成 · 直通失败，已自动重编码"
            oplog.log_job(status="done", title=job.title, out=str(job.out),
                          results=[str(p) for p in job.results], degraded=degraded,
                          elapsed_ms=int((time.time() - t_start) * 1000))
            return job
        except _Canceled:
            job.status, job.message = "canceled", "已取消"
            oplog.log_job(status="canceled", title=job.title, out=str(job.out),
                          elapsed_ms=int((time.time() - t_start) * 1000))
            return job
        except (FFmpegError, OSError) as exc:
            job.status, job.message = "failed", str(exc)
            oplog.log_error("run_job", exc, job=job.title, out=str(job.out),
                            src=str(job.src), elapsed_ms=int((time.time() - t_start) * 1000))
            return job

    @staticmethod
    def _tail(err: str, code: int) -> str:
        if not err:
            return f"ffmpeg 退出码 {code}"
        return "\n".join(err.strip().splitlines()[-5:])


class _Canceled(Exception):
    pass


def build_output_path(directory: Path, title: str, container: str = "mp4") -> Path:
    """输出路径：直接用剪辑文件夹名；重名时追加 -2、-3，绝不覆盖。"""
    from .utils import safe_filename

    return ensure_unique(Path(directory) / f"{safe_filename(title, 100)}.{container}")
