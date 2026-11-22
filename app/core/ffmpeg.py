"""ffmpeg / ffprobe 探测、调用、进度解析。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressCb = Callable[[float], None]  # 0.0 ~ 1.0


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _hide_window(kw: dict) -> dict:
    """Windows 下隐藏黑窗并支持独立进程组（便于取消）。"""
    if os.name == "nt":
        kw["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
    return kw


_TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}


def _popup_kwargs() -> dict:
    """Popen 用：需要管道。"""
    return _hide_window({"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                         "stdin": subprocess.DEVNULL, "bufsize": 1, **_TEXT})


def _run_kwargs(timeout: float | None = None) -> dict:
    """subprocess.run 用：输出需要捕获，不能自己传 stdout/stderr。"""
    kw = _hide_window({"capture_output": True, "timeout": timeout, **_TEXT})
    return kw


def _app_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        dirs += [exe_dir, exe_dir / "bin", exe_dir / "ffmpeg"]
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:                      # 空字符串会变成 Path(".")，污染候选列表
            mp = Path(meipass)
            dirs += [mp, mp / "bin", mp / "ffmpeg"]
    root = Path(__file__).resolve().parents[2]   # 项目根
    dirs += [root, root / "bin", root / "ffmpeg"]
    return dirs


def candidate_dirs(custom: str = "") -> list[Path]:
    out: list[Path] = []
    if custom:
        out.append(Path(custom))
    env = os.environ.get("M4S_FFMPEG_DIR") or os.environ.get("FFMPEG_DIR")
    if env:
        out.append(Path(env))
    out.extend(_app_dirs())
    if os.name == "nt":
        out += [
            Path(r"C:\ffmpeg\bin"),
            Path(r"C:\Program Files\ffmpeg\bin"),
            Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links")),
            Path(os.path.expandvars(r"%ProgramData%\chocolatey\bin")),
            Path(os.path.expandvars(r"%USERPROFILE%\scoop\shims")),
        ]
    return out


@dataclass
class MediaInfo:
    path: Path
    duration: float = 0.0
    width: int = 0
    height: int = 0
    vcodec: str = ""
    acodec: str = ""
    fps: float = 0.0
    bitrate: int = 0
    channels: int = 0
    v_streams: int = 0       # 视频流条数（以 codec_type 为准，不信 codec_name）
    a_streams: int = 0

    @property
    def has_video(self) -> bool:
        # 个别编码在 ffprobe 里 codec_name 为空但 codec_type 仍是 video，
        # 只看 vcodec 会把有画面的轨判成纯音频（预览黑屏、导出丢画面）。
        return self.v_streams > 0 or bool(self.vcodec)

    @property
    def has_audio(self) -> bool:
        return self.a_streams > 0 or bool(self.acodec)

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else ""


class FFmpegError(RuntimeError):
    pass


class FFmpeg:
    """ffmpeg 门面：一次探测，全局复用。"""

    def __init__(self, custom_dir: str = "") -> None:
        self.ffmpeg = ""
        self.ffprobe = ""
        self._version = ""
        self.locate(custom_dir)

    # ---------- 探测 ----------
    def locate(self, custom_dir: str = "") -> bool:
        for d in candidate_dirs(custom_dir):
            try:
                if not d.exists():
                    continue
            except OSError:
                continue
            f = d / _exe("ffmpeg")
            p = d / _exe("ffprobe")
            if f.is_file() and p.is_file():
                self.ffmpeg, self.ffprobe = str(f), str(p)
                return True
        for name in ("ffmpeg", "ffmpeg-latest", "ffmpeg-master-latest-win64-gpl"):
            found = shutil.which(name)
            if found:
                f = Path(found)
                p = f.with_name(_exe("ffprobe"))
                if p.is_file():
                    self.ffmpeg, self.ffprobe = str(f), str(p)
                    return True
                self.ffmpeg, self.ffprobe = str(f), ""
                return True
        self.ffmpeg = self.ffprobe = ""
        return False

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg) and Path(self.ffmpeg).exists()

    @property
    def version(self) -> str:
        if self._version or not self.available:
            return self._version
        try:
            res = subprocess.run([self.ffmpeg, "-hide_banner", "-version"],
                                 **_run_kwargs(15))
            first = (res.stdout or "").splitlines()[0]
            m = re.search(r"ffmpeg version (\S+)", first)
            self._version = m.group(1) if m else first[:60]
        except (OSError, subprocess.SubprocessError):
            self._version = "unknown"
        return self._version

    def encoders(self) -> set[str]:
        if not self.available:
            return set()
        try:
            res = subprocess.run([self.ffmpeg, "-hide_banner", "-encoders"],
                                 **_run_kwargs(25))
            return set(re.findall(r"^\s*[VAS][\w.]*\s+(\S+)", res.stdout or "", re.M))
        except (OSError, subprocess.SubprocessError):
            return set()

    # ---------- 探测媒体 ----------
    def probe(self, path: str | Path, timeout: int = 30) -> MediaInfo:
        info = MediaInfo(path=Path(path))
        probe = self.ffprobe or str(Path(self.ffmpeg).with_name(_exe("ffprobe")))
        if not probe or not Path(probe).exists():
            return info
        cmd = [probe, "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)]
        try:
            res = subprocess.run(cmd, **_run_kwargs(timeout))
        except (OSError, subprocess.SubprocessError):
            return info
        if res.returncode != 0:
            return info
        try:
            data = json.loads(res.stdout or "{}")
        except ValueError:
            return info
        fmt = data.get("format") or {}
        try:
            info.duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            info.duration = 0.0
        try:
            info.bitrate = int(float(fmt.get("bit_rate") or 0))
        except (TypeError, ValueError):
            info.bitrate = 0
        for st in data.get("streams") or []:
            kind = st.get("codec_type")
            if kind == "video":
                # 封面图会被 ffprobe 报成 video（attached_pic），不能算真正的视频轨
                disp = st.get("disposition") or {}
                if disp.get("attached_pic"):
                    continue
                info.v_streams += 1
                if not info.vcodec:
                    info.vcodec = st.get("codec_name") or ""
                    info.width = int(st.get("width") or 0)
                    info.height = int(st.get("height") or 0)
                    info.fps = _parse_fps(st.get("avg_frame_rate") or st.get("r_frame_rate") or "0/1")
                    if not info.duration:
                        info.duration = _safe_float(st.get("duration"))
            elif kind == "audio":
                info.a_streams += 1
                if not info.acodec:
                    info.acodec = st.get("codec_name") or ""
                    info.channels = int(st.get("channels") or 0)
                    if not info.duration:
                        info.duration = _safe_float(st.get("duration"))
        return info

    def keyframes(self, path: str | Path, a: float, b: float) -> list[float]:
        if not self.ffprobe:
            return []
        a = max(0.0, a)
        cmd = [self.ffprobe, "-v", "error", "-select_streams", "v:0",
               "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
               "-read_intervals", f"{a:.3f}%{b:.3f}", "-of", "csv=p=0", str(path)]
        try:
            res = subprocess.run(cmd, **_run_kwargs(25))
        except (OSError, subprocess.SubprocessError):
            return []
        out: list[float] = []
        for line in (res.stdout or "").splitlines():
            try:
                out.append(float(line.strip().split(",")[0]))
            except ValueError:
                continue
        return sorted(out)

    def keyframe_before(self, path: str | Path, t: float) -> float | None:
        ts = [x for x in self.keyframes(path, t - 6.0, t + 0.05) if x <= t + 0.001]
        return max(ts) if ts else None

    def nearest_keyframe(self, path: str | Path, t: float,
                         window: float = 4.0) -> float | None:
        """离 t 最近的关键帧（相等时取更早的），用于无损切点吸附。"""
        ts = self.keyframes(path, t - window, t + window)
        if not ts:
            return None
        before = [x for x in ts if x <= t + 0.001]
        after = [x for x in ts if x > t + 0.001]
        cands: list[float] = []
        if before:
            cands.append(before[-1])
        if after:
            cands.append(after[0])
        if not cands:
            return None
        return min(cands, key=lambda x: (round(abs(x - t), 3), x))

    # ---------- 执行 ----------
    def run(self, args: list[str], duration: float | None = None,
            on_progress: ProgressCb | None = None,
            cancel: threading.Event | None = None,
            timeout: float | None = None) -> tuple[int, str]:
        if not self.available:
            raise FFmpegError("未找到 ffmpeg，请在设置中指定 ffmpeg 所在目录")
        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-y",
               "-progress", "pipe:1", "-nostats", *[str(a) for a in args]]
        # 不设 text/bufsize=1：Windows 上 subprocess 的行缓冲只对写入生效，
        # 读 stdout 会先攒满 8 KB 才返回——ffmpeg 每 0.5 秒才吐一百多字节，
        # 进度条会好几十秒纹丝不动，看起来就是「卡在 0%」。
        # 这里用二进制 + readline，拿到一行就处理一行。
        proc = subprocess.Popen(cmd, **_hide_window({
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL, "bufsize": 0}))
        err_box: list[str] = []

        def drain() -> None:
            try:
                raw = proc.stderr.read() or b""
                err_box.append(raw.decode("utf-8", "replace"))
            except (ValueError, OSError):
                pass

        th = threading.Thread(target=drain, daemon=True)
        th.start()
        try:
            while True:
                raw = proc.stdout.readline() if proc.stdout else b""
                if not raw:
                    break
                if cancel is not None and cancel.is_set():
                    proc.terminate()
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line or on_progress is None or not duration:
                    continue
                key, _, val = line.partition("=")
                if key == "out_time_us" or key == "out_time_ms":
                    try:
                        sec = int(val) / 1_000_000.0
                    except ValueError:
                        continue
                    on_progress(max(0.0, min(1.0, sec / duration)))
                elif key == "out_time" and val:
                    sec = _parse_clock(val)
                    if sec is not None:
                        on_progress(max(0.0, min(1.0, sec / duration)))
        finally:
            try:
                proc.wait(timeout=timeout or 3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            th.join(timeout=3)
        code = proc.returncode
        if cancel is not None and cancel.is_set():
            return 130, "已取消"
        return code, (err_box[0] if err_box else "").strip()

    def run_checked(self, args: list[str], **kw) -> None:
        code, err = self.run(args, **kw)
        if code != 0:
            tail = "\n".join(err.splitlines()[-8:]) if err else f"退出码 {code}"
            raise FFmpegError(tail)


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_fps(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        d = float(den or 1)
        return round(float(num) / d, 3) if d else 0.0
    except (TypeError, ValueError):
        return 0.0


def _parse_clock(val: str) -> float | None:
    parts = val.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(val)
    except ValueError:
        return None
