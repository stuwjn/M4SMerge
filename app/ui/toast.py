"""右下角导出提示卡片。

一条导出弹一张，纵向堆叠、从底部往上长：

    ┌────────────────────────────┐
    │ ● clip_294100_2025…    42% │
    │   合并中                    │
    │ ▬▬▬▬▬▬▬▬▬░░░░░░░░░░░░░░░░  │
    └────────────────────────────┘

完成 → 变绿，停留 3 秒自动淡出；
失败 → 变红，**不自动消失**，要用户点 × 关掉（否则失败会被忽略）。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from . import theme
from .widgets import ElidedLabel, bold

CARD_W = 328
MAX_CARDS = 5
HOLD_MS = 3000          # 成功后停留时间


class ToastCard(QFrame):
    dismissed = Signal(str)          # key

    def __init__(self, key: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.state = "running"
        self.setObjectName("ToastCard")
        self.setFixedWidth(CARD_W)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 11)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.dot = QLabel("●")
        self.dot.setFixedWidth(10)
        f = self.dot.font()
        f.setPixelSize(10)
        self.dot.setFont(f)
        head.addWidget(self.dot, 0, Qt.AlignVCenter)

        self.name = ElidedLabel(title)
        bold(self.name, 12)
        head.addWidget(self.name, 1)

        self.pct = QLabel("0%")
        self.pct.setProperty("role", "meta")
        head.addWidget(self.pct, 0)

        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(18, 18)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setFocusPolicy(Qt.NoFocus)
        self.btn_close.setStyleSheet(
            "QPushButton{border:none;background:transparent;font-size:15px;padding:0;}")
        self.btn_close.clicked.connect(lambda: self.dismissed.emit(self.key))
        self.btn_close.hide()
        head.addWidget(self.btn_close, 0)
        lay.addLayout(head)

        self.sub = QLabel("准备中…")
        self.sub.setProperty("role", "meta")
        fs = self.sub.font()
        fs.setPixelSize(11)
        self.sub.setFont(fs)
        lay.addWidget(self.sub)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        self.bar.setStyleSheet("QProgressBar{border:none;background:transparent;}"
                               "QProgressBar::chunk{border-radius:1px;}")
        lay.addWidget(self.bar)
        self.restyle()

    # ---------- 状态 ----------
    def restyle(self) -> None:
        t = theme.current()
        color = {"running": t.accent, "done": t.ok, "failed": t.danger}[self.state]
        self.setStyleSheet(
            f"#ToastCard{{background:{t.surface};border:1px solid {t.line};"
            f"border-left:3px solid {color};border-radius:10px;}}")
        self.dot.setStyleSheet(f"color:{color};")
        self.bar.setStyleSheet(
            f"QProgressBar{{border:none;background:{t.surface_2};border-radius:1px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:1px;}}")

    def set_progress(self, value: float, msg: str = "") -> None:
        pct = max(0, min(100, int(round(value * 100))))
        if self.state == "running":
            self.pct.setText(f"{pct}%")
            self.bar.setValue(pct)
            if msg:
                self.sub.setText(msg)

    def finish(self, ok: bool, msg: str) -> None:
        self.state = "done" if ok else "failed"
        self.restyle()
        self.pct.setText("完成" if ok else "失败")
        self.sub.setText(msg or ("已导出" if ok else "导出失败"))
        if ok:
            self.bar.setValue(100)
            QTimer.singleShot(HOLD_MS, self._fade_out)
        else:
            self.bar.hide()
            self.btn_close.show()

    def _fade_out(self) -> None:
        if self.state != "done":
            return
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.finished.connect(lambda: self.dismissed.emit(self.key))
        self._anim = anim
        anim.start()


class ToastStack(QWidget):
    """浮层容器：贴在主窗口右下角，卡片自下而上堆叠。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._cards: list[ToastCard] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self._lay.addStretch(1)
        self.hide()

    # ---------- 对外 ----------
    def begin(self, key: str, title: str) -> None:
        self.drop(key)
        card = ToastCard(key, title, self)
        card.dismissed.connect(self.drop)
        self._lay.addWidget(card, 0, Qt.AlignRight)
        self._cards.append(card)
        while len(self._cards) > MAX_CARDS:
            self._remove(self._cards[0])
        self.show()
        self.raise_()
        self.reposition()

    def progress(self, key: str, value: float, msg: str = "") -> None:
        card = self.find(key)
        if card is not None:
            card.set_progress(value, msg)

    def finish(self, key: str, ok: bool, msg: str = "") -> None:
        card = self.find(key)
        if card is not None:
            card.finish(ok, msg)

    def find(self, key: str) -> ToastCard | None:
        for c in self._cards:
            if c.key == key:
                return c
        return None

    def drop(self, key: str) -> None:
        card = self.find(key)
        if card is not None:
            self._remove(card)

    def restyle(self) -> None:
        for c in self._cards:
            c.restyle()

    # ---------- 内部 ----------
    def _remove(self, card: ToastCard) -> None:
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._lay.removeWidget(card)
        card.setParent(None)
        card.deleteLater()
        if not self._cards:
            self.hide()
        else:
            self.reposition()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self._cards:
            return
        # 高度必须自己累加：新加的卡片还没进入 layout 的 sizeHint 计算，
        # 用 layout.sizeHint() 会拿到上一轮的高度，卡片会被压扁成一条线。
        gap = self._lay.spacing()
        h = sum(c.sizeHint().height() for c in self._cards) + gap * (len(self._cards) - 1)
        margin = 18
        self.setGeometry(parent.width() - CARD_W - margin,
                         parent.height() - h - margin, CARD_W, max(1, h))
