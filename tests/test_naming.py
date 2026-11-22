"""命名规则与「认不出的 m4s」自测：python tests/test_naming.py

本程序只认 Steam 的摆放方式。别的来源想用，不改代码，改名字——
这里的测试固定三件事：

· 规则与示例树讲得对（README、界面、剪贴板用的是同一份）
· 改名建议能给到「哪个文件改成什么」，顺序按数值不按字典
· 认不出的目录能被单独指出来，且不影响正常剪辑的扫描结果
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import naming  # noqa: E402
from app.core.ffmpeg import FFmpeg  # noqa: E402
from app.core.scanner import Scanner, dirs_with_m4s  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def touch(folder: Path, names: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"\x00" * 16)
    return folder


def main() -> int:
    tmp = Path(tempfile.mkdtemp())

    print("--- 规则文案 ---")
    tree = naming.TARGET_TREE
    for token in ("video\\", "init-stream0.m4s", "chunk-stream0-00001.m4s",
                  "init-stream1.m4s", "thumbnail.jpg"):
        check(f"示例树里有 {token}", token in tree)
    check("要点覆盖轨道号", any("轨号" in a for a, _ in naming.RULES))
    check("要点覆盖顺序数字", any("顺序" in a for a, _ in naming.RULES))
    check("一句话说清不用改设置", "不用改任何设置" in naming.ONE_LINER)

    print()
    print("--- 改名建议：只有一轨 ---")
    d1 = touch(tmp / "flat", ["00001.m4s", "00002.m4s", "00010.m4s"])
    p1 = naming.plan_renames(d1)
    check("给出对照", p1 is not None and p1.count == 3, str(p1.count if p1 else None))
    got = dict(p1.rows) if p1 else {}
    check("00001 改成 chunk-stream0-00001", got.get("00001.m4s") == "chunk-stream0-00001.m4s")
    check("00010 排第三不排第二", got.get("00010.m4s") == "chunk-stream0-00003.m4s",
          str(got.get("00010.m4s")))

    d2 = touch(tmp / "with_init", ["seg-1.m4s", "seg-2.m4s", "init.mp4"])
    p2 = naming.plan_renames(d2)
    got2 = dict(p2.rows) if p2 else {}
    check("init.mp4 改成 init-stream0", got2.get("init.mp4") == "init-stream0.m4s",
          str(got2.get("init.mp4")))
    check("init 不参与 chunk 编号", got2.get("seg-1.m4s") == "chunk-stream0-00001.m4s",
          str(got2.get("seg-1.m4s")))
    check("提示两轨要分堆", "stream1" in (p2.note if p2 else ""), (p2.note if p2 else "")[:24])

    print()
    print("--- 改名建议：文件很多、有多轨 ---")
    many = ["v%03d.m4s" % i for i in range(1, 21)]
    p3 = naming.plan_renames(touch(tmp / "many", many))
    check("对照被折叠到 8 行以内", p3 is not None and p3.count <= 8,
          str(p3.count if p3 else None))
    check("折叠行说明还剩多少", any("其余" in a or "其余" in b for a, b in (p3.rows if p3 else [])))

    d4 = touch(tmp / "two_tracks", ["init-v.mp4", "init-a.mp4", "1.m4s", "2.m4s"])
    p4 = naming.plan_renames(d4)
    check("多初始化段不硬猜轨号", p4 is not None and p4.rows == [], str(p4.rows if p4 else None))
    check("多初始化段给出人工分堆提示", "两条轨" in (p4.note if p4 else ""),
          (p4.note if p4 else "")[:24])

    empty = tmp / "empty"
    empty.mkdir()
    check("空目录不给建议", naming.plan_renames(empty) is None)

    print()
    print("--- 复制到剪贴板 ---")
    text = naming.clipboard_text([p1])
    check("含示例树", "chunk-stream0-00001.m4s" in text)
    check("含现有对照", "00001.m4s → chunk-stream0-00001.m4s" in text)

    print()
    print("--- 扫描：认不出的目录被单独指出 ---")
    clips = tmp / "gamerecordings" / "clips"
    from tests.steam_fixture import build
    build(clips, count=2, seconds=3)

    deep = touch(clips / "wrong" / "video" / "sub" / "deep",
                 ["00001.m4s", "00002.m4s"])
    recs, bad = Scanner(FFmpeg()).scan_ex([clips])
    check("正常剪辑照常扫到", len(recs) == 2, str(len(recs)))
    check("深层目录被标记出来", len(bad) == 1, str([u.folder.name for u in bad]))
    check("标记的是那个深层目录", bad and bad[0].folder == deep)
    check("数对了分片个数", bad and bad[0].m4s == 2, str(bad[0].m4s if bad else None))
    check("说清了层得太深", bad and "层得太深" in bad[0].reason,
          bad[0].reason if bad else "")
    check("正常剪辑的分片目录不算未识别",
          all("fg_" not in u.folder.name and "bg_" not in u.folder.name for u in bad))

    print()
    print("--- 扫描：dirs_with_m4s 只做只读探测 ---")
    found = dirs_with_m4s(clips)
    check("能找到含分片的目录", len(found) >= 3, str(len(found)))
    check("探测不改文件", all(p.exists() for p in found))

    ui_checks(tmp, bad[0] if bad else None)

    print()
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


def ui_checks(tmp: Path, sample) -> None:
    """界面上的提示链路：空提示多一个「怎么改名」、标题旁挂未识别计数。"""
    print()
    print("--- 界面提示 ---")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])

    from app.ui.dialogs import NamingHelpDialog
    from app.ui.library import EmptyClipsDialog, LibraryPage

    dlg = EmptyClipsDialog(None, searched=[], unmatched=[sample] if sample else [])
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    check("空提示标题说清「认不出来」", any("认不出来" in t for t in texts),
          str([t for t in texts if "认不出来" in t][:1]))
    check("空提示给出具体数量", any("2 个 m4s" in t for t in texts),
          str([t for t in texts if "m4s" in t][:1]))
    check("多出「怎么改名」按钮", not dlg.btn_naming.isHidden())
    dlg.btn_naming.click()
    check("点它返回 NAMING 动作", dlg.action == EmptyClipsDialog.NAMING, str(dlg.action))

    dlg2 = EmptyClipsDialog(None, searched=["D:\\Steam\\clips"])
    check("没有未识别时不显示「怎么改名」", dlg2.btn_naming.isHidden())
    check("没有未识别时仍是「没有找到剪辑」", "没有找到剪辑" in dlg2.windowTitle(),
          dlg2.windowTitle())

    plan = naming.plan_renames(tmp / "flat")
    nd = NamingHelpDialog([plan] if plan else [], None)
    nd.btn_copy.click()
    clip = QGuiApplication.clipboard().text()
    check("说明里能复制做法", "chunk-stream0-00001.m4s" in clip and "video\\" in clip)
    check("复制后按钮给出反馈", nd.btn_copy.text() == "已复制", nd.btn_copy.text())
    check("空建议也能打开说明", NamingHelpDialog([], None).windowTitle() != "")

    page = LibraryPage()
    page.set_unmatched([sample] if sample else [])
    check("列表标题旁挂未识别计数", not page.naming_hint.isHidden())
    check("计数文字带数量", "2 个 m4s 未识别" in page.naming_hint.text(),
          page.naming_hint.text())
    fired: list[int] = []
    page.namingHelpRequested.connect(lambda: fired.append(1))
    page.naming_hint.click()
    check("点计数能发出请求", fired == [1], str(fired))
    page.set_unmatched([])
    check("清空后计数消失", page.naming_hint.isHidden())
    page.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    sys.exit(main())
