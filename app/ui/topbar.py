"""顶部导航：64px 高、居中导航（18px/700）、右侧 200x32 搜索框与图标。

对齐 YesPlayMusic Navbar.vue：
  height 64px；padding 左右 10vw（<1336px 时 5vw）；
  导航项 18px/700、圆角 6px、hover 出 secondary-bg-for-transparent、active 仅变 primary 色；
  搜索框 32px 高 / 200px 宽 / 圆角 8px。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ..core.settings import APP_NAME
from . import theme


def logo_pixmap(size: int = 26) -> QPixmap:
    t = theme.current()
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(t.accent))
    p.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
    # 三条横杠：上面两段（分片）收到下面一整条（合并结果）
    p.setBrush(QColor("#ffffff"))
    bar_h = size * 0.085
    p.drawRoundedRect(QRectF(size * 0.24, size * 0.28, size * 0.22, bar_h),
                      bar_h / 2, bar_h / 2)
    p.drawRoundedRect(QRectF(size * 0.54, size * 0.28, size * 0.22, bar_h),
                      bar_h / 2, bar_h / 2)
    p.drawRoundedRect(QRectF(size * 0.24, size * 0.545, size * 0.52, bar_h),
                      bar_h / 2, bar_h / 2)
    p.end()
    return pm


class TopBar(QWidget):
    navChanged = Signal(int)
    searchChanged = Signal(str)
    themeToggled = Signal()
    settingsRequested = Signal()

    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(64)
        self._buttons: list[QPushButton] = []

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(24, 0, 24, 0)
        self._lay.setSpacing(0)

        # 左：品牌（对应原项目左侧前进后退区）
        left = QWidget()
        lh = QHBoxLayout(left)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(8)
        self.logo = QLabel()
        self.logo.setPixmap(logo_pixmap(24))
        self.name = QLabel(APP_NAME)
        self.name.setObjectName("LogoText")
        lh.addWidget(self.logo)
        lh.addWidget(self.name)
        lh.addStretch(1)

        # 中：导航
        nav = QWidget()
        nh = QHBoxLayout(nav)
        nh.setContentsMargins(0, 0, 0, 0)
        nh.setSpacing(0)
        for i, text in enumerate(items):
            b = QPushButton(text)
            b.setProperty("nav", True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, idx=i: self.set_page(idx))
            nh.addWidget(b)
            self._buttons.append(b)

        # 右：搜索 + 图标
        right = QWidget()
        rh = QHBoxLayout(right)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(2)
        rh.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索剪辑 / AppID")
        self.search.setClearButtonEnabled(True)
        self.search.setFocusPolicy(Qt.ClickFocus)
        self.search.setFixedSize(200, 32)
        self.search.textChanged.connect(self.searchChanged.emit)
        rh.addWidget(self.search)
        self.btn_theme = QPushButton()
        self.btn_theme.setProperty("iconBtn", True)
        self.btn_theme.setToolTip("切换深浅色")
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.setFocusPolicy(Qt.NoFocus)
        self.btn_theme.setFixedSize(32, 32)
        self.btn_theme.setIconSize(QSize(17, 17))
        self.btn_theme.clicked.connect(self.themeToggled.emit)
        rh.addWidget(self.btn_theme)
        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setFixedSize(32, 32)
        self.btn_settings.setProperty("iconBtn", True)
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setFocusPolicy(Qt.NoFocus)
        self.btn_settings.clicked.connect(self.settingsRequested.emit)
        rh.addWidget(self.btn_settings)

        self._lay.addWidget(left, 1)
        self._lay.addWidget(nav, 0)
        self._lay.addWidget(right, 1)

        self.set_page(0)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        # 原项目 main { padding: 0 10vw }，窄屏（<1336px）落到 5vw
        pad = max(24, int(self.width() * 0.05))
        self._lay.setContentsMargins(pad, 0, pad, 0)

    def set_page(self, index: int) -> None:
        for i, b in enumerate(self._buttons):
            b.setProperty("active", i == index)
            b.style().unpolish(b)
            b.style().polish(b)
        self.navChanged.emit(index)

    def set_theme_icon(self, mode: str) -> None:
        """切到深色时显示太阳（可切回），反之显示月亮。"""
        name = "sun" if mode == "dark" else "moon"
        icon = theme.asset(f"{name}-{mode}.png")
        self.btn_theme.setIcon(QIcon(icon))
