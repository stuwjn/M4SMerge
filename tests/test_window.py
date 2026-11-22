"""主窗口自测：python tests/test_window.py

盯住几条最容易做错的规则：

· 多选导出 = 逐条产出多个 mp4（**不是**合并成一个）
· 勾选 2 条 → 队列 2 个任务 → 输出目录里 2 个文件
· 单条导出只产生 1 个任务
· 扫描为空时弹「没找到剪辑」对话框
· 关闭窗口会清空会话临时文件
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.ffmpeg import FFmpeg  # noqa: E402
from app.core.scanner import Scanner  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from tests.steam_fixture import build  # noqa: E402

app = QApplication.instance() or QApplication([])
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def pump(sec: float = 0.15) -> None:
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.01)


def wait_until(fn, timeout: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if fn():
            return True
        time.sleep(0.02)
    return False


def make_window(tmp: Path, clips: Path, out: Path) -> MainWindow:
    p = tmp / "settings.json"
    p.write_text(json.dumps({"theme": "dark", "scan_roots": [str(clips)],
                             "output_dir": str(out), "auto_scan_on_start": False}),
                 "utf-8")
    w = MainWindow(Settings(p))
    w.resize(1080, 720)
    return w


def main() -> int:
    theme.apply(app, theme.DARK)
    ff = FFmpeg()
    if not ff.available:
        print("[SKIP] 本机没有 ffmpeg")
        return 0

    # 上一次异常退出可能在 temp 里留下半成品，先清空，后面「没有残留」的断言才成立
    from app.core.settings import app_temp_dir
    shutil.rmtree(app_temp_dir(), ignore_errors=True)

    tmp = Path(tempfile.mkdtemp())
    clips = build(tmp / "clips", count=4, seconds=4)
    recs = Scanner(ff).scan([clips])
    check("准备：扫到 4 条", len(recs) == 4, str(len(recs)))
    if len(recs) < 4:
        return 1

    print()
    print("--- 两个页面 ---")
    out1 = tmp / "out1"
    out1.mkdir()
    w = make_window(tmp, clips, out1)
    w.show()
    w.library.set_recordings(recs)
    pump(0.2)
    check("只有两个页面", w.pages.count() == 2, str(w.pages.count()))
    check("导航只有「剪辑 / 导出队列」", len(w.topbar._buttons) == 2,
          str([b.text() for b in w.topbar._buttons]))
    check("没有底部栏", not hasattr(w, "bottom"))
    check("没有播放器", not hasattr(w, "player"))

    print()
    print("--- 单条导出 ---")
    w.export_clips([recs[0]])
    pump(0.1)
    check("队列里 1 个任务", len(w.queue.jobs) == 1, str(len(w.queue.jobs)))
    check("自动跳到队列页", w.pages.currentIndex() == 1)
    check("弹出 1 张提示卡片", len(w.toasts._cards) == 1, str(len(w.toasts._cards)))
    ok = wait_until(lambda: all(j.status == "done" for j in w.queue.jobs), 25)
    check("任务完成", ok, str([(j.status, j.message) for j in w.queue.jobs]))
    files1 = list(out1.glob("*.mp4"))
    check("输出目录 1 个文件", len(files1) == 1, str([p.name for p in files1]))

    print()
    print("--- 多选导出 = 多个文件（不是合并） ---")
    out2 = tmp / "out2"
    out2.mkdir()
    w.settings.set("output_dir", str(out2))
    batch = [recs[1], recs[2], recs[3]]
    w.export_clips(batch)
    pump(0.1)
    check("队列新增 3 个任务", len(w.queue.jobs) == 4, str(len(w.queue.jobs)))
    check("3 张卡片同时在跑", len(w.toasts._cards) >= 3, str(len(w.toasts._cards)))
    ok = wait_until(lambda: all(j.status in ("done", "failed") for j in w.queue.jobs), 40)
    check("全部结束", ok)
    done = [j for j in w.queue.jobs[1:]]
    check("三条都是 done", all(j.status == "done" for j in done),
          str([(j.title[-8:], j.status) for j in done]))
    files2 = sorted(out2.glob("*.mp4"))
    check("输出目录是 3 个独立文件", len(files2) == 3, str([p.name for p in files2]))
    check("文件名各不相同", len({p.stem for p in files2}) == 3)
    check("文件名不等于剪辑名相加（没有合并成一个）",
          not any(len(p.stem) > 60 for p in files2), str([p.stem for p in files2]))
    sizes = [p.stat().st_size for p in files2]
    check("每个文件都有实际内容", all(s > 100_000 for s in sizes),
          str([s // 1024 for s in sizes]))

    print()
    print("--- 完成后临时文件被回收 ---")
    from app.core.settings import app_temp_dir
    tdir = app_temp_dir()

    def temp_clean() -> bool:
        return not tdir.exists() or not any(tdir.glob("*.mp4"))

    # 回收发生在 jobFinished 槽里，机器忙时可能晚一拍，给它 5 秒而不是死等 0.5 秒
    gone = wait_until(temp_clean, 5)
    leftovers = [p.name for p in tdir.glob("*.mp4")] if tdir.exists() else []
    check("程序 temp 里没有残留的合并片", gone and leftovers == [], str(leftovers))

    print()
    print("--- 扫描为空 ---")
    empty = tmp / "empty-clips"
    empty.mkdir()
    w2 = make_window(tmp / "w2" if (tmp / "w2").exists() else tmp, empty, out1)
    w2.settings.set("scan_roots", [str(empty)])
    w2.show()
    w2.library.set_recordings([])
    pump(0.1)
    check("空列表显示空状态", w2.library.empty.isVisible())
    check("批量条收起", not w2.library.bulk.isVisible())
    from app.ui.library import EmptyClipsDialog
    dlg = EmptyClipsDialog(w2, searched=[str(empty)])
    check("空提示对话框有三个按钮",
          all(b.text() for b in (dlg.btn_refresh, dlg.btn_pick, dlg.btn_cancel)),
          str([dlg.btn_refresh.text(), dlg.btn_pick.text(), dlg.btn_cancel.text()]))
    check("按钮文案符合要求",
          dlg.btn_refresh.text() == "刷新"
          and dlg.btn_pick.text() == "手动选择文件夹"
          and dlg.btn_cancel.text() == "取消")
    dlg.btn_cancel.click()
    check("取消返回 0", dlg.action == 0)
    dlg.deleteLater()

    print()
    print("--- 关闭清理 ---")
    w.close()
    pump(0.2)
    check("关窗后 temp 为空", not tdir.exists() or not any(tdir.iterdir()),
          str(list(tdir.iterdir()) if tdir.exists() else []))
    w2.close()
    pump(0.1)

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
