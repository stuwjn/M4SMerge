"""造一套和 Steam 一模一样的剪辑目录，供自测用。

    <root>/clip_<appid>_<日期>_<时间>/
        clip.pb
        thumbnail.jpg
        video/<fg|bg>_…/
            session.mpd
            init-stream0.m4s, chunk-stream0-00001.m4s …
            init-stream1.m4s, chunk-stream1-00001.m4s …

用真 ffmpeg 造分片（H.264 + AAC），所以合并出来的结果可以用 ffprobe 校验。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _ffmpeg() -> str:
    from app.core.ffmpeg import FFmpeg
    ff = FFmpeg()
    if not ff.ffmpeg:
        raise RuntimeError("找不到 ffmpeg，无法构造测试夹具")
    return ff.ffmpeg


def make_clip(root: Path, name: str, seconds: int = 6, size: str = "640x360",
              prefix: str = "fg", with_mpd: bool = True,
              with_thumb: bool = True, freq: int = 440) -> Path:
    """造一条剪辑，返回 clip 目录。"""
    ff = _ffmpeg()
    clip = Path(root) / name
    vdir = clip / "video" / f"{prefix}_{name[5:]}"
    vdir.mkdir(parents=True, exist_ok=True)
    args = [
        ff, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
        "-c:v", "libopenh264", "-b:v", "800k", "-g", "30",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "dash", "-seg_duration", "2", "-use_template", "1",
        "-use_timeline", "0",
        "-init_seg_name", "init-stream$RepresentationID$.m4s",
        "-media_seg_name", "chunk-stream$RepresentationID$-$Number%05d$.m4s",
        str(vdir / "session.mpd"),
    ]
    subprocess.run(args, check=True)
    if not with_mpd:
        # 模拟用户只拷了分片、丢了清单：程序应能按文件名把轨拼回去
        (vdir / "session.mpd").unlink(missing_ok=True)
    if with_thumb:
        # 封面从清单抽一帧（Steam 自己也是存一张 jpg）
        source = (vdir / "session.mpd") if (vdir / "session.mpd").exists() else None
        if source is not None:
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", "1", "-i", str(source),
                            "-frames:v", "1", "-vf", "scale=320:-2",
                            str(clip / "thumbnail.jpg")], check=False)
    (clip / "clip.pb").write_bytes(b"\x08\x01")     # Steam 的元数据占位
    return clip


def build(root: Path, count: int = 3, seconds: int = 6) -> Path:
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        make_clip(root, f"clip_{294100 + i}_{20250810 + i}_12{i:02d}00",
                  seconds=seconds + i * 2, freq=440 + i * 80)
    return root
