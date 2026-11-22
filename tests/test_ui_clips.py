"""界面自测：python tests/test_ui_clips.py

重点验证需求里最容易做错的地方：

· 多选导出是**逐个导出多个文件**，不是合并成一个
· 点行只高亮，不触发任何动作
· 行尾「导出」只管自己那一行
· 全选复选框点一下就全选（不是先到半选）
· 空列表时批量条收起、空状态显示
· 搜索与排序不改动勾选状态
· 几百条也不卡（重建 + 勾选耗时）
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.ffmpeg import FFmpeg  # noqa: E402
from app.core.recording import Recording  # noqa: E402
from app.core.scanner import Scanner  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.library import LibraryPage  # noqa: E402
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


def main() -> int:
    theme.apply(app, theme.LIGHT)
    ff = FFmpeg()
    if not ff.available:
        print("[SKIP] 本机没有 ffmpeg")
        return 0

    tmp = Path(tempfile.mkdtemp())
    clips = build(tmp / "clips", count=5, seconds=4)
    recs = Scanner(ff).scan([clips])
    check("准备：扫到 5 条", len(recs) == 5, str(len(recs)))

    page = LibraryPage()
    page.resize(1000, 700)
    page.show()
    page.set_recordings(recs)
    pump(0.3)

    print()
    print("--- 初始状态 ---")
    check("行数正确", len(page._rows) == 5)
    check("默认一条都没勾", page.selected() == [])
    check("「导出所选」不可用", not page.btn_export_sel.isEnabled())
    check("批量条可见（有数据时）", page.bulk.isVisible())
    check("列表可见、空状态隐藏", page.list.isVisible() and not page.empty.isVisible())

    print()
    print("--- 单条导出按钮 ---")
    got: list = []
    page.exportRequested.connect(lambda r: got.append(r))
    row = page._rows[recs[0].key]
    row.btn.click()
    pump(0.05)
    check("点行尾「导出」发出这一条", len(got) == 1 and got[0].key == recs[0].key,
          str([r.title for r in got]))
    check("单条导出不改勾选状态", page.selected() == [])

    print()
    print("--- 点行只高亮 ---")
    got.clear()
    page._on_row_clicked(recs[2].key)
    pump(0.05)
    check("点行不触发导出", got == [])
    check("点行会切换当前项", page.current() is not None
          and page.current().key == recs[2].key)

    print()
    print("--- 勾选两条 → 批量导出两个文件 ---")
    page._rows[recs[0].key].check.setChecked(True)
    page._rows[recs[1].key].check.setChecked(True)
    pump(0.05)
    check("已选 2 项", len(page.selected()) == 2, str(len(page.selected())))
    check("提示文字跟着变", "2" in page.sel_info.text(), page.sel_info.text())
    check("「导出所选」可用", page.btn_export_sel.isEnabled())
    check("按钮上标了数量", "2" in page.btn_export_sel.text(), page.btn_export_sel.text())
    check("全选显示半选态", page.check_all.checkState() == Qt.PartiallyChecked)

    many: list = []
    page.exportManyRequested.connect(lambda rs: many.append(list(rs)))
    page.btn_export_sel.click()
    pump(0.05)
    check("批量导出发出 2 条", len(many) == 1 and len(many[0]) == 2,
          str([len(x) for x in many]))
    check("发出的是两条独立剪辑（不是合并成一条）",
          many and many[0][0].key != many[0][1].key)

    print()
    print("--- 全选 ---")
    page.check_all.click()          # 半选 → 全选
    pump(0.05)
    check("点一下变全选", len(page.selected()) == 5, str(len(page.selected())))
    check("全选框显示已全选", page.check_all.checkState() == Qt.Checked)
    page.check_all.click()          # 全选 → 全不选
    pump(0.05)
    check("再点一下全不选", page.selected() == [])
    check("全选框回到未选", page.check_all.checkState() == Qt.Unchecked)

    print()
    print("--- 搜索 / 排序不改勾选 ---")
    page._rows[recs[0].key].check.setChecked(True)
    page._rows[recs[3].key].check.setChecked(True)
    pump(0.05)
    page.set_query("clip")
    pump(0.3)
    check("搜索后勾选保留", len(page.selected()) == 2, str(len(page.selected())))
    page.set_query("zzzz-no-match")
    pump(0.3)
    check("无结果时列表隐藏、提示出现",
          not page.list.isVisible() and page.empty.isVisible())
    check("无结果时勾选仍保留（只是看不见）", len(page.selected()) == 2)
    page.set_query("")
    pump(0.3)
    check("清空搜索后恢复", len(page._rows) == 5)

    page.sort.setCurrentIndex(1)     # 时长最长
    pump(0.1)
    durations = [r.duration for r in
                 [page._rows[k].rec for k in page._rows]]
    check("按时长排序生效", durations == sorted(durations, reverse=True), str(durations))
    check("排序不改勾选", len(page.selected()) == 2, str(len(page.selected())))

    print()
    print("--- 空状态 ---")
    page.set_recordings([])
    pump(0.1)
    check("列表隐藏", not page.list.isVisible())
    check("空状态显示", page.empty.isVisible())
    check("批量条收起", not page.bulk.isVisible())
    check("排序也收起", not page.sort.isVisible())
    check("标题计数为 0", "0" in page.count.text(), page.count.text())

    print()
    print("--- 600 条规模 ---")
    base = recs[0]
    many_recs = []
    for i in range(600):
        r = Recording(key=f"k{i}", path=base.path, kind="dash",
                      title=f"clip_{i:06d}_20250810_1200{i % 60:02d}",
                      mtime=base.mtime - i, size=base.size,
                      tracks=base.tracks, declared_duration=base.declared_duration)
        many_recs.append(r)
    t0 = time.time()
    page.set_recordings(many_recs)
    pump(0.06)
    check("首屏立刻有内容（不等 600 条全部建完）", len(page._rows) >= 30,
          f"{len(page._rows)} 行 / {int((time.time() - t0) * 1000)} ms")
    deadline = time.time() + 6
    while len(page._rows) < 600 and time.time() < deadline:
        pump(0.05)
    ms = int((time.time() - t0) * 1000)
    check("600 条最终全部建出来", len(page._rows) == 600, str(len(page._rows)))
    check("600 条总耗时 < 3s", ms < 3000, f"{ms} ms（含事件循环）")
    t0 = time.time()
    for r in many_recs[:100]:
        page._rows[r.key].check.setChecked(True)   # 走真实信号路径
    page._sync_selection()
    ms = int((time.time() - t0) * 1000)
    check("勾选 100 条 < 300ms", ms < 300, f"{ms} ms")
    check("计数正确", len(page.selected()) == 100, str(len(page.selected())))

    page.deleteLater()
    pump(0.05)

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
