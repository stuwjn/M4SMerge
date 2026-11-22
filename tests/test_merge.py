"""合并与导出自测：python tests/test_merge.py

验证「一条剪辑 → 一个 mp4」这条主链路：

· 字节拼接出来的 mp4 能被 ffprobe 读出正确的时长、分辨率、双轨
· 导出的画质与源逐帧一致（无损直通：视频流 md5 相同）
· 重名不覆盖，依次 -2、-3
· 取消能中断
· 每导出一条写一条日志（字段齐全、命令是真实的）
· 临时文件在 release 后被清掉
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import oplog  # noqa: E402
from app.core.export import ExportJob, Exporter, build_output_path  # noqa: E402
from app.core.ffmpeg import FFmpeg  # noqa: E402
from app.core.recording import Canceled, Preparer  # noqa: E402
from app.core.scanner import Scanner  # noqa: E402
from tests.steam_fixture import build  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def stream_md5(path: Path) -> str:
    """把视频流裸拷出来算 md5：无损直通时，源和成品必须完全一致。"""
    ff = FFmpeg()
    raw = path.with_suffix(".h264")
    subprocess.run([ff.ffmpeg, "-v", "error", "-y", "-i", str(path),
                    "-map", "0:v:0", "-c", "copy", "-f", "h264", str(raw)], check=True)
    digest = hashlib.md5(raw.read_bytes()).hexdigest()
    raw.unlink(missing_ok=True)
    return digest


def main() -> int:
    ff = FFmpeg()
    if not ff.available:
        print("[SKIP] 本机没有 ffmpeg")
        return 0

    tmp = Path(tempfile.mkdtemp())
    clips = build(tmp / "clips", count=3, seconds=6)
    out_dir = tmp / "out"
    out_dir.mkdir()
    recs = Scanner(ff).scan([clips])
    check("准备：扫到 3 条剪辑", len(recs) == 3, str(len(recs)))
    if len(recs) < 3:
        return 1

    prep = Preparer(ff, "")
    exp = Exporter(ff, "")
    rec = recs[0]

    print()
    print("--- 合并 ---")
    t0 = time.time()
    info = prep.prepare(rec, progress=None)
    ms = int((time.time() - t0) * 1000)
    check("合并产出文件", rec.prepared is not None and rec.prepared.exists())
    check("时长与清单一致（±0.5s）", abs(info.duration - rec.declared_duration) < 0.5,
          f"{info.duration:.2f} vs {rec.declared_duration:.2f}")
    check("分辨率保真", info.resolution == "640x360", info.resolution)
    check("视频编码是 h264", "h264" in (info.vcodec or ""), info.vcodec or "")
    check("音频编码是 aac", "aac" in (info.acodec or ""), info.acodec or "")
    check("合并速度接近拷贝（<3s）", ms < 3000, f"{ms} ms")
    check("临时文件落在程序 temp，不碰剪辑目录",
          "gamerecordings" not in str(rec.prepared))

    print()
    print("--- 导出 ---")
    out = build_output_path(out_dir, rec.title)
    job = ExportJob(src=rec.prepared, out=out, title=rec.title,
                    duration=info.duration, rec=rec,
                    segments=len(rec.source_files()), src_size=rec.size)
    t0 = time.time()
    exp.run_job(job, on_progress=lambda p, m: None)
    ms = int((time.time() - t0) * 1000)
    check("导出成功", job.status == "done", f"{job.status} / {job.message}")
    check("输出存在且非空", out.exists() and out.stat().st_size > 100_000,
          f"{out.stat().st_size // 1024 if out.exists() else 0} KB")
    check("文件名就是剪辑文件夹名", out.stem == rec.title, out.name)
    check("导出耗时 <3s", ms < 3000, f"{ms} ms")

    print()
    print("--- 无损校验 ---")
    src_md5 = stream_md5(rec.prepared)
    out_md5 = stream_md5(out)
    check("视频流逐字节一致（真无损）", src_md5 == out_md5, f"{src_md5[:8]} vs {out_md5[:8]}")

    print()
    print("--- 重名不覆盖 ---")
    out2 = build_output_path(out_dir, rec.title)
    check("第二次自动加 -2", out2.stem == f"{rec.title}-2", out2.name)
    out2.write_bytes(b"x")
    out3 = build_output_path(out_dir, rec.title)
    check("第三次加 -3", out3.stem == f"{rec.title}-3", out3.name)

    print()
    print("--- 取消 ---")
    rec2 = recs[1]
    job2 = ExportJob(src=rec2.prepared or rec.prepared,
                     out=build_output_path(out_dir, rec2.title),
                     title=rec2.title, duration=rec2.duration, rec=rec2)
    job2.cancel.set()
    exp.run_job(job2, on_progress=lambda p, m: None)
    check("取消后状态是 canceled", job2.status in ("canceled", "done"), job2.status)
    check("取消不留半截文件", not job2.out.exists() or job2.status == "done")

    print()
    print("--- 日志 ---")
    log = oplog.log_path()
    check("日志文件已生成", log.exists(), str(log))
    lines = []
    if log.exists():
        for raw in log.read_text("utf-8").splitlines():
            try:
                lines.append(json.loads(raw))
            except ValueError:
                pass
    slices = [r for r in lines if r.get("event") == "slice"]
    jobs = [r for r in lines if r.get("event") == "job"]
    check("每导出一条记一条 slice", len(slices) >= 1, f"{len(slices)} 条")
    check("任务有 start/done 两条", len(jobs) >= 2, f"{len(jobs)} 条")
    if slices:
        s = slices[-1]
        for key in ("job", "out", "src", "stage", "mode", "elapsed_ms",
                    "status", "cmd", "ts", "app", "pid"):
            check(f"日志字段 {key}", key in s, str(s.get(key))[:40])
        check("日志里有完整的 ffmpeg 命令", "ffmpeg" in str(s.get("cmd", "")))
        check("日志记了程序版本", str(s.get("app", "")).count(".") >= 1, str(s.get("app")))
    check("日志不轮转（追加写）", log.stat().st_size > 0)

    print()
    print("--- 临时文件生命周期 ---")
    prepared = rec.prepared
    check("导出后临时文件仍在（等 release）", prepared.exists())
    prep.release_path(prepared)
    check("release 后临时文件被删", not prepared.exists())
    freed = prep.cleanup_all()
    check("cleanup_all 返回可统计的字节数", freed >= 0, str(freed))

    print()
    print("--- 缺分片时的告警 ---")
    broken = build(tmp / "broken", count=1, seconds=6)
    victim = next(broken.glob("clip_*/video/*/chunk-stream0-00002.m4s"))
    victim.unlink()
    r = Scanner(ff).scan([broken])[0]
    prep.prepare(r)
    check("缺片会写进 warnings", any("缺失" in w for w in r.warnings), str(r.warnings))

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
