"""设计令牌 + QSS。

严格对齐 YesPlayMusic 源码（src/assets/css/global.scss 与各组件 scoped 样式）：
  浅色  --color-body-bg #ffffff / --color-text #000
        --color-primary #335eea / --color-primary-bg #eaeffd
        --color-secondary #7a7a7b / --color-secondary-bg #f5f5f7
        --color-navbar-bg rgba(255,255,255,.86)（原实现用 backdrop-filter 毛玻璃）
        分隔线统一 rgba(128,128,128,.18)，主按钮为「浅蓝底 + 蓝字」而非实心蓝
  深色  #222222 / #ffffff / #323232，primary 不变

Qt 无 backdrop-filter，用半透明同色近似毛玻璃。
CSS 的 opacity 无法在 Qt 表达，预先混色为十六进制。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def asset(name: str) -> str:
    """资源绝对路径（QSS url 需要正斜杠）。"""
    return (Path(__file__).resolve().parent.parent / "resources" / name).as_posix()


@dataclass(frozen=True)
class Tokens:
    mode: str
    bg: str            # --color-body-bg
    surface: str       # 浮层（下拉、弹窗）
    surface_2: str     # --color-secondary-bg
    text: str          # --color-text
    text_88: str       # text @ .88
    text_2: str        # text @ .68（辅助文字）
    text_3: str        # text @ .58（弱化文字）
    line: str          # rgba(128,128,128,.18) 混色后
    line_soft: str     # 更淡的分隔（导航/播放条边缘补偿）
    accent: str        # --color-primary
    accent_soft: str   # --color-primary-bg
    accent_text: str   # 强调块上的文字
    fill: str          # secondary-bg-for-transparent 混色
    fill_accent: str   # primary-bg-for-transparent 混色
    nav_bg: str        # navbar 半透明底
    danger: str
    warn: str
    ok: str
    stage: str         # 视频舞台底色


LIGHT = Tokens(
    mode="light",
    bg="#ffffff",
    surface="#ffffff",
    surface_2="#f5f5f7",
    text="#000000",
    text_88="#1f1f1f",
    text_2="#525252",
    text_3="#6b6b6b",
    line="#dcdcdc",
    line_soft="#f0f0f0",
    accent="#335eea",
    accent_soft="#eaeffd",
    accent_text="#335eea",
    fill="#efeff1",
    fill_accent="#eef3ff",
    nav_bg="rgba(255, 255, 255, 235)",
    danger="#d93f43",
    warn="#9a6700",
    ok="#1a7f43",
    stage="#000000",
)

DARK = Tokens(
    mode="dark",
    bg="#222222",
    surface="#2a2a2a",
    surface_2="#323232",
    text="#ffffff",
    text_88="#e4e4e4",
    text_2="#b8b8b8",
    text_3="#a2a2a2",
    line="#3d3d3d",
    line_soft="#2b2b2b",
    accent="#335eea",
    accent_soft="#2b3a63",
    accent_text="#a9bcff",
    # 深色下 primary-bg-for-transparent 是白色 12% -> 叠在 #222 上
    fill="#313131",
    fill_accent="#38393d",
    nav_bg="rgba(34, 34, 34, 235)",
    danger="#f2555a",
    warn="#e0a33a",
    ok="#3ec07a",
    stage="#000000",
)


CURRENT: Tokens = LIGHT


def current() -> Tokens:
    return CURRENT


def qss(t: Tokens) -> str:
    return f"""
/* ========== 基础 ========== */
* {{
    font-family: "Barlow", "Microsoft YaHei UI", "PingFang SC",
                 "Segoe UI", "Noto Sans CJK SC", sans-serif;
    font-size: 14px;
    color: {t.text};
    outline: none;
}}
QWidget {{ background: transparent; }}
QMainWindow, QDialog {{ background: {t.bg}; }}

/* ========== 顶部导航（高 64，无边框，靠留白分隔） ========== */
#TopBar {{ background: {t.bg}; border: none; }}
#LogoText {{ font-size: 17px; font-weight: 700; letter-spacing: -0.2px; }}

QPushButton[nav="true"] {{
    background: transparent; border: none; border-radius: 6px;
    padding: 6px 10px; margin: 0 12px;
    color: {t.text}; font-size: 18px; font-weight: 700;
}}
QPushButton[nav="true"]:hover {{ background: {t.fill}; }}
QPushButton[nav="true"][active="true"] {{ color: {t.accent}; }}
QPushButton[nav="true"][active="true"]:hover {{ background: transparent; }}

QPushButton[iconBtn="true"] {{
    background: transparent; border: none; border-radius: 7px;
    padding: 8px; margin: 4px; color: {t.text}; font-size: 16px;
    min-width: 16px; min-height: 16px;
}}
QPushButton[iconBtn="true"]:hover {{ background: {t.fill}; }}
QPushButton[iconBtn="true"]:focus {{ background: transparent; }}

/* ========== 搜索框（高 32 / 圆角 8 / secondary-bg-for-transparent） ========== */
QLineEdit#Search {{
    background: {t.fill}; border: 1px solid transparent;
    border-radius: 8px; padding: 0 10px; color: {t.text};
    font-size: 14px; font-weight: 400;
    selection-background-color: {t.accent}; selection-color: #ffffff;
}}
QLineEdit#Search:focus {{
    background: {t.fill_accent}; border-color: transparent; color: {t.accent};
}}

/* ========== 按钮 ==========
   普通 = secondary-bg 填充、无边框
   主按钮（accent）= primary-bg 底 + primary 字（原项目 ButtonTwoTone）
   ghost = 透明，hover 出浅底（原项目 ButtonIcon） */
QPushButton {{
    background: {t.surface_2}; border: none;
    border-radius: 8px; padding: 8px 16px; color: {t.text};
    font-size: 14px; font-weight: 500;
}}
QPushButton:hover {{ background: {t.line}; }}
QPushButton:pressed {{ background: {t.line}; }}
QPushButton:disabled {{ color: {t.text_3}; background: {t.surface_2}; }}

QPushButton[accent="true"] {{
    background: {t.accent_soft}; color: {t.accent_text};
    border: none; font-weight: 600; padding: 9px 20px; font-size: 15px;
}}
QPushButton[accent="true"]:hover {{ background: {t.accent_soft}; color: {t.accent_text}; }}
QPushButton[accent="true"]:pressed {{ background: {t.accent_soft}; }}
QPushButton[accent="true"]:disabled {{ background: {t.surface_2}; color: {t.text_3}; }}

/* 列表行内的「导出」：比通用主按钮窄一点的内边距，字号 15 也不挤；
   hover 变实心蓝，和浅蓝底形成明确反馈 */
QPushButton[rowAction="true"] {{
    background: {t.accent_soft}; color: {t.accent_text};
    border: none; border-radius: 9px;
    padding: 8px 18px; font-size: 15px; font-weight: 600;
}}
QPushButton[rowAction="true"]:hover {{ background: {t.accent}; color: #ffffff; }}
QPushButton[rowAction="true"]:pressed {{ background: {t.accent}; color: #ffffff; }}
QPushButton[rowAction="true"]:disabled {{ background: {t.surface_2}; color: {t.text_3}; }}

QPushButton[ghost="true"] {{
    background: transparent; border: none; color: {t.text_2};
    padding: 8px 14px; font-weight: 500;
}}
QPushButton[ghost="true"]:hover {{ background: {t.fill}; color: {t.text}; }}
QPushButton[ghost="true"]:disabled {{ color: {t.text_3}; background: transparent; }}

/* 标题旁的小提醒：可点，但不跟按钮抢注意力 */
QPushButton[link="true"] {{
    background: transparent; border: none; color: {t.accent};
    padding: 3px 8px; margin: 0 0 0 2px; font-size: 12.5px; font-weight: 500;
}}
QPushButton[link="true"]:hover {{ background: {t.accent_soft}; color: {t.accent_text}; }}

QPushButton[play="true"] {{
    background: {t.accent}; color: #ffffff; border: none;
    border-radius: 21px; min-width: 42px; max-width: 42px;
    min-height: 42px; max-height: 42px; padding: 0; font-size: 13px;
}}
QPushButton[play="true"]:hover {{ background: {t.accent}; }}
QPushButton[play="true"]:disabled {{ background: {t.surface_2}; color: {t.text_3}; }}

QPushButton[toggle="true"] {{
    background: transparent; border: none; border-radius: 8px;
    padding: 6px 11px; color: {t.text_3}; font-size: 13px; font-weight: 500;
}}
QPushButton[toggle="true"]:hover {{ background: {t.fill}; color: {t.text_2}; }}
QPushButton[toggle="true"]:checked {{
    background: {t.accent_soft}; color: {t.accent}; font-weight: 600;
}}

/* ========== 筛选标签（圆角 8，激活为灰底 + opacity 提升） ========== */
QPushButton[tab="true"] {{
    background: transparent; border: none; border-radius: 8px;
    padding: 8px 14px; margin-right: 14px;
    color: {t.text_3}; font-size: 15px; font-weight: 600;
}}
QPushButton[tab="true"]:hover {{ background: {t.surface_2}; color: {t.text_88}; }}
QPushButton[tab="true"][active="true"] {{
    background: {t.surface_2}; color: {t.text_88}; font-weight: 600;
}}

/* ========== 列表 ========== */
QListWidget, QTableWidget, QTreeWidget {{
    background: transparent; border: none; outline: none;
}}
QListWidget[role="box"] {{
    background: {t.surface_2}; border: none; border-radius: 12px; padding: 4px;
}}
QListWidget::item {{ border-radius: 12px; padding: 0; margin: 0; }}
QListWidget::item:hover {{ background: {t.fill}; }}
QListWidget::item:selected {{ background: transparent; color: {t.accent}; }}
QListWidget::item:selected:hover {{ background: transparent; }}

QTableWidget::item {{ padding: 0 10px; border: none; }}
QTableWidget::item:hover {{ background: {t.surface_2}; }}
QTableWidget::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}

QHeaderView::section {{
    background: transparent; border: none;
    border-bottom: 1px solid {t.line};
    padding: 8px 10px; color: {t.text_3};
    font-weight: 600; font-size: 12.5px;
}}

/* ========== 滚动条（8px / thumb rgba(128,128,128,.38) / radius 10） ========== */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {t.line}; border-radius: 4px; min-height: 40px; margin: 1px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.text_3}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{
    background: {t.line}; border-radius: 4px; min-width: 40px;
}}

/* ========== 滑块（2px 轨 + 12px 圆点） ========== */
QSlider::groove:horizontal {{ height: 3px; background: {t.line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {t.accent}; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {t.accent}; }}

/* ========== 下拉框 ========== */
QComboBox {{
    background: {t.fill}; border: none;
    border-radius: 9px; padding: 8px 30px 8px 14px; color: {t.text};
    font-size: 14px; min-height: 22px;
}}
QComboBox:hover {{ background: {t.line}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{
    image: url("{asset("arrow-dark.png" if t.mode == "dark" else "arrow-light.png")}");
    width: 11px; height: 7px; margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: {t.surface}; border: 1px solid {t.line}; border-radius: 10px;
    padding: 5px; outline: none;
    selection-background-color: {t.surface_2}; selection-color: {t.text};
}}

/* ========== 输入框 ========== */
QLineEdit, QSpinBox {{
    background: {t.fill}; border: 1px solid transparent;
    border-radius: 8px; padding: 7px 10px; color: {t.text}; font-size: 14px;
    selection-background-color: {t.accent}; selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus {{ background: {t.fill_accent}; border-color: transparent; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QSpinBox::up-arrow, QSpinBox::down-arrow {{ width: 0; height: 0; }}

/* ========== 卡片 / 舞台 ========== */
QFrame[card="true"] {{
    background: {t.surface_2}; border: none; border-radius: 16px;
}}
QFrame[stage="true"] {{ background: {t.stage}; border: none; border-radius: 14px; }}

/* ========== 文本角色 ========== */
QLabel[role="h1"] {{ font-size: 32px; font-weight: 700; letter-spacing: -0.5px; }}
QLabel[role="h2"] {{ font-size: 18px; font-weight: 600; }}
QLabel[role="pageTitle"] {{ font-size: 24px; font-weight: 700; letter-spacing: -0.3px; }}
QLabel[role="dur"] {{ color: {t.text_2}; font-size: 15px; }}
QLabel[role="h3"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {t.text_2}; }}
QLabel[role="dim"] {{ color: {t.text_3}; }}
QLabel[role="meta"] {{ color: {t.text_2}; font-size: 13px; }}
QLabel[role="barTitle"] {{ font-size: 16px; font-weight: 600; color: {t.text_88}; }}
QLabel[role="barSub"] {{ color: {t.text_3}; font-size: 12px; }}
QLabel[role="mono"] {{
    font-family: "Consolas", "SF Mono", monospace; font-size: 13px;
    color: {t.text_2};
}}
QLabel[role="pill"] {{
    background: {t.surface_2}; border-radius: 9px; padding: 4px 11px;
    color: {t.text_2}; font-size: 12.5px;
}}
QLabel[role="accentpill"] {{
    background: {t.accent_soft}; border-radius: 9px; padding: 4px 11px;
    color: {t.accent}; font-size: 12.5px; font-weight: 600;
}}

/* ========== 底部播放条（高 64，顶部 2px 进度线，无边框） ========== */
#BottomBar {{ background: {t.bg}; border: none; }}
QProgressBar#BarProgress {{
    background: transparent; border: none; height: 2px;
    text-align: center; color: transparent;
}}
QProgressBar#BarProgress::chunk {{ background: {t.accent}; }}

QProgressBar {{
    background: {t.line}; border: none; border-radius: 2px;
    height: 4px; color: transparent;
}}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 2px; }}

/* ========== 复选 / 菜单 / 提示 ========== */
QCheckBox {{ color: {t.text_88}; spacing: 8px; font-size: 13.5px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {t.line}; background: {t.surface_2};
}}
QCheckBox::indicator:checked {{
    background: {t.accent}; border-color: {t.accent};
    image: url("{asset("check.png")}");
}}

QMenu {{
    background: {t.surface}; border: 1px solid {t.line};
    border-radius: 12px; padding: 6px;
}}
QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 8px; color: {t.text}; }}
QMenu::item:selected {{ background: {t.surface_2}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 5px 8px; }}

QToolTip {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.line};
    border-radius: 8px; padding: 6px 9px; font-size: 13px;
}}

/* ========== 容器 ========== */
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: {t.bg}; border-top: 1px solid {t.line_soft}; color: {t.text_3}; }}
QStatusBar::item {{ border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QGroupBox {{
    border: 1px solid {t.line_soft}; border-radius: 14px;
    margin-top: 14px; padding: 12px 14px 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 5px;
    color: {t.text_2}; font-weight: 600; font-size: 13px;
}}
"""


def apply(app, tokens: Tokens) -> None:
    global CURRENT
    from PySide6.QtGui import QColor, QPalette

    CURRENT = tokens

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(tokens.bg))
    pal.setColor(QPalette.WindowText, QColor(tokens.text))
    pal.setColor(QPalette.Base, QColor(tokens.surface))
    pal.setColor(QPalette.AlternateBase, QColor(tokens.surface_2))
    pal.setColor(QPalette.Text, QColor(tokens.text))
    pal.setColor(QPalette.Button, QColor(tokens.surface_2))
    pal.setColor(QPalette.ButtonText, QColor(tokens.text))
    pal.setColor(QPalette.Highlight, QColor(tokens.accent_soft))
    pal.setColor(QPalette.HighlightedText, QColor(tokens.text))
    pal.setColor(QPalette.ToolTipBase, QColor(tokens.surface))
    pal.setColor(QPalette.ToolTipText, QColor(tokens.text))
    pal.setColor(QPalette.PlaceholderText, QColor(tokens.text_3))
    app.setPalette(pal)
    app.setStyleSheet(qss(tokens))
