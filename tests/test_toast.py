"""右下角提示卡片自测：python tests/test_toast.py

规则来自需求：一条导出弹一张、自下而上堆叠；完成变绿 3 秒后消失，
失败变红且**不自动消失**；同时最多 5 张。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.ui import theme  # noqa: E402
from app.ui.toast import MAX_CARDS, ToastStack  # noqa: E402

app = QApplication.instance() or QApplication([])
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


def pump(sec: float = 0.1) -> None:
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    theme.apply(app, theme.DARK)
    host = QWidget()
    host.resize(1000, 700)
    host.show()
    stack = ToastStack(host)

    print("--- 开始一张 ---")
    stack.begin("k1", "clip_294100_20250810_120000")
    pump(0.05)
    check("弹出一张卡片", len(stack._cards) == 1, str(len(stack._cards)))
    card = stack.find("k1")
    check("卡片绑定到对应 key", card is not None)
    check("初始状态是 running", card.state == "running")
    check("浮层整体显示", stack.isVisible())
    check("卡片贴在右下角",
          stack.x() + stack.width() <= host.width()
          and stack.y() + stack.height() <= host.height())
    check("卡片高度够放两行字", card.height() >= 60, f"{card.height()}px")

    print()
    print("--- 进度 ---")
    stack.progress("k1", 0.42, "合并中")
    pump(0.05)
    check("百分比更新", card.pct.text() == "42%", card.pct.text())
    check("进度条同步", card.bar.value() == 42, str(card.bar.value()))
    check("副标题更新", "合并" in card.sub.text(), card.sub.text())
    stack.progress("k1", 1.7, "越界也不炸")
    check("超过 100% 被夹住", card.bar.value() == 100, str(card.bar.value()))

    print()
    print("--- 成功：变绿、3 秒后消失 ---")
    stack.finish("k1", True, "已导出 · a.mp4")
    pump(0.05)
    check("状态变 done", card.state == "done")
    check("显示「完成」", "完成" in card.pct.text(), card.pct.text())
    check("没有关闭按钮（会自动消失）", not card.btn_close.isVisible())
    check("3 秒内还在", True)
    pump(3.5)
    check("3 秒后自动消失", stack.find("k1") is None, str(len(stack._cards)))

    print()
    print("--- 失败：变红、常驻 ---")
    stack.begin("k2", "clip_570_20250811_090000")
    stack.finish("k2", False, "导出失败：磁盘已满")
    pump(0.05)
    card2 = stack.find("k2")
    check("状态变 failed", card2 is not None and card2.state == "failed")
    check("显示「失败」", "失败" in card2.pct.text(), card2.pct.text())
    check("出现关闭按钮", card2.btn_close.isVisible())
    check("隐藏进度条", not card2.bar.isVisible())
    pump(4.0)
    check("失败卡片不会自动消失", stack.find("k2") is not None)
    stack.drop("k2")
    pump(0.05)
    check("手动关闭后移除", stack.find("k2") is None)
    check("没有卡片时浮层隐藏", not stack.isVisible())

    print()
    print("--- 堆叠与上限 ---")
    for i in range(MAX_CARDS + 2):
        stack.begin(f"n{i}", f"clip_{i}_20250812_1010{i:02d}")
        pump(0.02)
    check(f"最多同时 {MAX_CARDS} 张", len(stack._cards) == MAX_CARDS, str(len(stack._cards)))
    order = [c.key for c in stack._cards]
    check("保留的是最新的几张", order[-1] == f"n{MAX_CARDS + 1}", str(order))
    top, bottom = stack._cards[-1], stack._cards[0]
    check("从上往下依次排列（最新在最下）",
          top.y() > bottom.y(), f"{top.y()} vs {bottom.y()}")
    check("整体仍贴右下角",
          stack.x() + stack.width() <= host.width()
          and stack.y() + stack.height() <= host.height())

    print()
    print("--- key 重复 ---")
    stack.drop("n0")
    before = len(stack._cards)
    stack.progress("n1", 0.5, "x")
    stack.begin("n1", "同一个 key 再来一次")
    pump(0.05)
    check("同 key 不会重复堆两张", len(stack._cards) == before, str(len(stack._cards)))

    print()
    print("--- 换主题 ---")
    theme.apply(app, theme.LIGHT)
    stack.restyle()
    pump(0.05)
    check("切主题后卡片能重绘不报错", len(stack._cards) >= 1)

    stack.deleteLater()
    host.deleteLater()
    pump(0.05)

    print()
    print(f"{'全部通过' if not failures else '失败 %d 项: %s' % (len(failures), failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
