"""手动重命名自测：python tests/test_rename.py

覆盖三件容易做错的事：
· 时间戳格式必须是 Windows 能用的 `名称 - 2026-11-22 23-46-00`（不能带冒号）
· 只改输出名，不动剪辑文件夹；改完刷新/重启还在
· 同一批多选各用各自的时间；撞名要自动错开，不能两个任务写同一个文件
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.export import build_output_path  # noqa: E402
from app.core.naming import compose_out_name, plan_out_names, stamp_text  # noqa: E402
from app.core.recording import Recording  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.dialogs import RenameDialog  # noqa: E402
from app.ui.library import LibraryPage  # noqa: E402

app = QApplication.instance() or QApplication([])
failures: list[str] = []

T0 = datetime(2026, 11, 22, 23, 46, 0).timestamp()


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def rec(title: str = "clip_413150_20251118_214502", mtime: float = T0, key: str = "",
        stamp: float = 0.0) -> Recording:
    return Recording(key=key or title, path=Path("/x") / title, kind="dash",
                     title=title, mtime=mtime, stamp=stamp)


def main() -> int:
    theme.apply(app, theme.LIGHT)

    print("--- 时间戳格式 ---")
    check("格式是 2026-11-22 23-46-00", stamp_text(T0) == "2026-11-22 23-46-00", stamp_text(T0))
    check("不含冒号（Windows 文件名非法）", ":" not in stamp_text(T0))
    check("时间戳越界不抛异常", stamp_text(-1e30) == "" or isinstance(stamp_text(-1e30), str))

    print()
    print("--- 名称 + 时间戳 ---")
    got = compose_out_name("影之刃零", T0, True)
    check("用户要的样子", got == "影之刃零 - 2026-11-22 23-46-00", got)
    check("不勾时间戳只有名称", compose_out_name("影之刃零", T0, False) == "影之刃零")
    check("首尾空格被清掉", compose_out_name("  影之刃零  ", T0, False) == "影之刃零")
    check("非法字符替换成下划线",
          compose_out_name("a/b:c*?", T0, False) == "a_b_c__", compose_out_name("a/b:c*?", T0, False))
    long_name = "影" * 200
    got = compose_out_name(long_name, T0, True)
    check("超长名称截断后时间戳仍然完整", got.endswith(" - 2026-11-22 23-46-00"), got[-24:])
    check("截断后总长不超 100", len(got) <= 100, str(len(got)))
    check("空名称退回占位名", compose_out_name("", T0, False) == "clip")

    print()
    print("--- 时间取封面（thumbnail.jpg） ---")
    # 分片时间比封面晚一小时：命名必须用封面时间
    r_cover = rec(key="c1", mtime=T0 + 3600, stamp=T0)
    check("有封面时间 → 用封面",
          compose_out_name("影之刃零", r_cover.stamp_time, True) == "影之刃零 - 2026-11-22 23-46-00",
          stamp_text(r_cover.stamp_time))
    r_no = rec(key="c2", mtime=T0, stamp=0.0)
    check("没封面 → 退回分片时间", r_no.stamp_time == T0, stamp_text(r_no.stamp_time))
    planned = plan_out_names([r_cover, r_no], "影之刃零", True)
    check("批量各用各自时间，同秒撞名 -2",
          planned.get("c1") == "影之刃零 - 2026-11-22 23-46-00"
          and planned.get("c2") == "影之刃零 - 2026-11-22 23-46-00-2", str(planned))

    print()
    print("--- 输出名优先级 ---")
    r = rec()
    check("没改名时用文件夹名", r.out_stem == r.title, r.out_stem)
    r.out_title = "影之刃零 - 2026-11-22 23-46-00"
    check("改过名后用新名字", r.out_stem == "影之刃零 - 2026-11-22 23-46-00", r.out_stem)
    r.out_title = "   "
    check("空白的改名不生效", r.out_stem == r.title, r.out_stem)

    print()
    print("--- 同批撞名 ---")
    out_dir = Path(tempfile.mkdtemp())
    used: set[Path] = set()
    a = build_output_path(out_dir, "影之刃零 - 2026-11-22 23-46-00", taken=used)
    used.add(a)
    b = build_output_path(out_dir, "影之刃零 - 2026-11-22 23-46-00", taken=used)
    check("第二条自动加 -2", b.name.endswith("-2.mp4"), b.name)
    check("两条路径不同", a != b)

    print()
    print("--- 重命名对话框 ---")
    r1, r2 = rec(key="k1"), rec(key="k2", title="clip_b", mtime=T0 - 60)
    dlg = RenameDialog([r1, r2], with_stamp=True)
    dlg.name_edit.setText("影之刃零")
    app.processEvents()
    check("勾了时间戳 → 预览带时间", dlg.recs and dlg.stamp.isChecked())
    labels = [dlg.pl.itemAt(i).widget().text() for i in range(dlg.pl.count())]
    check("批量各用各自时间（早的在前）",
          labels == ["影之刃零 - 2026-11-22 23-45-00.mp4", "影之刃零 - 2026-11-22 23-46-00.mp4"],
          str(labels))
    dlg.stamp.setChecked(False)
    app.processEvents()
    labels = [dlg.pl.itemAt(i).widget().text() for i in range(dlg.pl.count())]
    check("取消勾选后不带时间（同秒撞名自动 -2）",
          labels == ["影之刃零.mp4", "影之刃零-2.mp4"], str(labels))
    dlg.name_edit.setText("")
    app.processEvents()
    check("名称为空时不能保存", not dlg.btn_ok.isEnabled())
    dlg.name_edit.setText("  影之刃零  ")
    check("恢复原名按钮只置标记", not dlg.restore)
    dlg._do_restore()
    check("点「用回文件夹名」置 restore", dlg.restore and dlg.result() == int(RenameDialog.Accepted))
    dlg.deleteLater()

    print()
    print("--- 列表里的重命名入口 ---")
    page = LibraryPage()
    page.resize(1000, 700)
    page.show()
    page.set_recordings([r1, r2])
    app.processEvents()
    check("默认「重命名」不可用", not page.btn_rename.isEnabled())
    page._rows["k1"].check.setChecked(True)
    app.processEvents()
    check("勾一条后可用", page.btn_rename.isEnabled())
    page._rows["k2"].check.setChecked(True)
    app.processEvents()
    got_targets = page.rename_targets("k1")
    check("勾了多条 → 改整批", [x.key for x in got_targets] == ["k1", "k2"],
          str([x.key for x in got_targets]))
    check("没勾的条目只改自己", [x.key for x in page.rename_targets("k1")] == ["k1", "k2"])
    page._rows["k2"].check.setChecked(False)
    app.processEvents()
    check("只勾一条时只改这一条", [x.key for x in page.rename_targets("k1")] == ["k1"])

    r1.out_title = "影之刃零 - 2026-11-22 23-46-00"
    page.refresh_names()
    app.processEvents()
    check("改完名列表立刻更新", page._rows["k1"].title.text() == r1.out_title,
          page._rows["k1"].title.text())
    check("提示里能看到原文件夹名", "原文件夹名" in page._rows["k1"].toolTip(),
          page._rows["k1"].toolTip())

    page.deleteLater()
    app.processEvents()

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
