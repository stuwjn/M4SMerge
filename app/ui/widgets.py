"""通用小部件：圆角封面、省略号标签、分隔线。"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from . import theme


class CoverLabel(QWidget):
    """圆角封面。没有图时画一个「空画框」，而不是播放三角——

    这东西现在只是缩略图，不代表「点我播放」。
    """

    def __init__(self, size: QSize, radius: int = 8, parent=None) -> None:
        super().__init__(parent)
        self._pm = QPixmap()
        self._radius = radius
        self.setFixedSize(size)

    def set_pixmap(self, pm: QPixmap) -> None:
        self._pm = pm
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.setClipPath(path)
        if self._pm.isNull():
            p.fillRect(rect, QColor(t.surface_2))
            # 空画框：16:9 的细边矩形 + 顶部一小段「胶片齿孔」
            inner = rect.adjusted(rect.width() * 0.18, rect.height() * 0.22,
                                  -rect.width() * 0.18, -rect.height() * 0.22)
            p.setPen(QPen(QColor(t.text_3), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(inner, 3, 3)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.text_3))
            notch = max(2.0, inner.width() * 0.10)
            p.drawRoundedRect(QRectF(inner.left() + inner.width() * 0.16,
                                     inner.top() + inner.height() * 0.42,
                                     notch, inner.height() * 0.16), 1, 1)
        else:
            scaled = self._pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
            p.drawPixmap(rect, scaled,
                         QRectF((scaled.width() - rect.width()) / 2,
                                (scaled.height() - rect.height()) / 2,
                                rect.width(), rect.height()))


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._full = text

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._apply()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._apply()

    def _apply(self) -> None:
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.ElideRight, max(20, self.width())))


def hairline() -> QWidget:
    w = QWidget()
    w.setFixedHeight(1)
    w.setStyleSheet(f"background:{theme.current().line};")
    return w


def bold(label: QLabel, px: int, weight: QFont.Weight = QFont.DemiBold) -> None:
    f = QFont(label.font())
    f.setPixelSize(px)
    f.setWeight(weight)
    label.setFont(f)
