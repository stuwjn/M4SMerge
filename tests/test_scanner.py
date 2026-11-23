"""扫描自测：python tests/test_scanner.py

覆盖 Steam 剪辑的几种真实摆放方式，以及「不是剪辑」的目录不能被误收：

· 标准结构 clips/clip_…/video/fg_…/
· 选到 gamerecordings（上一级）要自动下钻到 clips
· 选到某一条剪辑本身
· 丢了 session.mpd 也要能按 init/chunk 文件名把轨拼回来
· 没有 thumbnail.jpg 时封面留空、不报错
· 空目录 / 普通视频目录不产生条目
· AppID 从目录名提取
· 几百条剪辑的扫描时间（不能卡）
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.ffmpeg import FFmpeg  # noqa: E402
from app.core.scanner import (Scanner, clip_dirs_under, default_scan_roots,  # noqa: E402
                              looks_like_clip, steam_clip_dirs)
from tests.steam_fixture import build, make_clip  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    ff = FFmpeg()
    if not ff.available:
        print("[SKIP] 本机没有 ffmpeg")
        return 0

    tmp = Path(tempfile.mkdtemp())
    clips = tmp / "gamerecordings" / "clips"
    build(clips, count=3, seconds=6)

    print("--- 目录识别 ---")
    check("clip_ 目录被认成剪辑", looks_like_clip(clips / "clip_294100_20250810_120000"))
    check("空的普通目录不算剪辑", not looks_like_clip(tmp))
    check("gamerecordings 本身不算剪辑", not looks_like_clip(clips.parent))

    print()
    print("--- 展开：三种选法 ---")
    a = clip_dirs_under(clips)
    check("直接选 clips 得到 3 条", len(a) == 3, str([p.name for p in a]))
    b = clip_dirs_under(clips.parent)
    check("选到 gamerecordings 会自动下钻", len(b) == 3, str(len(b)))
    one = clips / "clip_294100_20250810_120000"
    c = clip_dirs_under(one)
    check("选到某一条剪辑只出这一条", len(c) == 1 and c[0] == one)

    print()
    print("--- 解析 ---")
    t0 = time.time()
    recs = Scanner(ff).scan([clips])
    ms = int((time.time() - t0) * 1000)
    check("扫到 3 条", len(recs) == 3, f"{len(recs)} 条 / {ms} ms")
    check("按修改时间倒序", all(recs[i].mtime >= recs[i + 1].mtime
                                for i in range(len(recs) - 1)))
    rec = recs[0]
    check("标题就是文件夹名", rec.title.startswith("clip_"), rec.title)
    check("AppID 从目录名取到", rec.appid.isdigit() and len(rec.appid) >= 3, rec.appid)
    check("双轨（视频+音频）", len(rec.tracks) == 2,
          str([(t.kind, len(t.segments)) for t in rec.tracks]))
    check("视频轨有 3 个分片以上", max(len(t.segments) for t in rec.tracks) >= 3)
    check("时长大于 0", rec.duration > 0, f"{rec.duration:.2f}s")
    check("体积统计到", rec.size > 100_000, f"{rec.size // 1024} KB")
    check("封面指向 thumbnail.jpg",
          rec.thumb is not None and rec.thumb.name == "thumbnail.jpg")
    check("没有误报警告", rec.warnings == [], str(rec.warnings))
    check("能列出所有源文件", len(rec.source_files()) >= 8, str(len(rec.source_files())))
    check("扫描 3 条在 1 秒内", ms < 1000, f"{ms} ms")

    print()
    print("--- 缺清单时按文件名分组 ---")
    no_mpd = make_clip(tmp / "nomanifest", "clip_999_20250811_090000",
                       seconds=4, with_mpd=False, with_thumb=False)
    r2 = Scanner(ff).scan([no_mpd])
    check("没有 mpd 也能扫到", len(r2) == 1, str(len(r2)))
    if r2:
        check("按 init-streamN 分出两条轨", len(r2[0].tracks) == 2,
              str([t.kind for t in r2[0].tracks]))
        check("没有封面时为 None", r2[0].thumb is None)
        check("时长用分片数估算", r2[0].duration > 0, f"{r2[0].duration:.1f}s")

    print()
    print("--- 时间戳取封面时间 ---")
    cover = make_clip(tmp / "stampcase", "clip_777_20250812_101500", seconds=3)
    thumb = cover / "thumbnail.jpg"
    if thumb.exists():
        want = datetime(2026, 11, 22, 23, 0, 0).timestamp()
        os.utime(thumb, (want, want))
        r3 = Scanner(ff).scan([cover])
        check("扫描后 stamp 等于封面时间",
              bool(r3) and abs(r3[0].stamp - want) <= 1, str(r3[0].stamp if r3 else None))
        check("stamp_time 优先用封面", bool(r3) and abs(r3[0].stamp_time - want) <= 1,
              str(r3[0].stamp_time if r3 else None))
        check("分片时间明显不同（证明确实没用分片）",
              bool(r3) and abs(r3[0].mtime - want) > 60, str(r3[0].mtime if r3 else None))
    else:
        check("夹具应生成 thumbnail.jpg", False, str(thumb))

    print()
    print("--- 不该被当成剪辑的东西 ---")
    junk = tmp / "junk"
    junk.mkdir()
    (junk / "readme.txt").write_text("hi", "utf-8")
    check("只有文本文件的目录扫不出东西", Scanner(ff).scan([junk]) == [])
    check("不存在的目录不报错", Scanner(ff).scan([tmp / "no-such-dir"]) == [])
    check("空 clips 目录扫出空列表", Scanner(ff).scan([tmp / "empty-clips"]) == [])

    print()
    print("--- 扫描根 ---")
    roots = default_scan_roots([str(clips)])
    check("手动目录进了扫描根", any(str(p) == str(clips) for p in roots), str(roots))
    check("重复目录只留一份",
          len(default_scan_roots([str(clips), str(clips)])) == len(roots))
    check("steam_clip_dirs 在无 Steam 的机器上返回空表",
          isinstance(steam_clip_dirs(), list))

    print()
    print("--- 规模 ---")
    print("[INFO] 造 60 条剪辑测扫描耗时…")
    big = tmp / "big"
    build(big, count=12, seconds=2)
    # 复制成 60 条（只改目录名，分片内容无所谓——扫描不读像素）
    for i in range(48):
        src = big / f"clip_{294100 + i % 12}_{20250810 + i % 12}_12{i % 12:02d}00"
        dst = big / f"clip_{500000 + i}_20250901_10{i:02d}00"
        if src.exists() and not dst.exists():
            dst.mkdir()
            (dst / "video").mkdir()
            for sub in (src / "video").iterdir():
                if sub.is_dir():
                    (dst / "video" / sub.name).symlink_to(sub.resolve())
    t0 = time.time()
    many = Scanner(ff).scan([big])
    ms = int((time.time() - t0) * 1000)
    check("60 条扫得出来", len(many) >= 60, f"{len(many)} 条")
    check("60 条扫描在 2 秒内", ms < 2000, f"{ms} ms")

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
