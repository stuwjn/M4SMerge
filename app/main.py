"""程序入口：python -m app.main / run.bat"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.settings import APP_NAME, Settings
from app.ui import theme
from app.ui.main_window import MainWindow


def _set_windows_app_id() -> None:
    """Windows 任务栏分组用：源码运行时也能显示自己的图标而不是 python.exe。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "M4SMerge.Desktop.1")
    except Exception:
        pass


def main() -> int:
    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")

    settings = Settings()
    mode = settings.get("theme", "light")
    theme.apply(app, theme.DARK if mode == "dark" else theme.LIGHT)

    for base in (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])),
                 Path(__file__).resolve().parent):
        icon_path = base / "app" / "resources" / "app.ico"
        if not icon_path.exists():
            icon_path = base / "resources" / "app.ico"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    win = MainWindow(settings)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
