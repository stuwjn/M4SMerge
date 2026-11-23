"""设置、手动重命名、以及「认不出的 m4s 怎么改名」三个对话框（浅色极简风）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..core import naming
from ..core.naming import RenamePlan
from ..core.settings import Settings, app_temp_dir, default_output_dir
from . import theme
from .widgets import ElidedLabel


def section(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "h3")
    return lab


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("role", "meta")
    lab.setWordWrap(True)
    return lab


class _HintList(QListWidget):
    """空列表时显示占位文字。"""

    def __init__(self, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self.setProperty("role", "box")

    def paintEvent(self, ev) -> None:  # noqa: N802
        super().paintEvent(ev)
        if self.count() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor(theme.current().text_3))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, self._placeholder)
            p.end()


class NamingHelpDialog(QDialog):
    """「认不出的 m4s 怎么改名」。

    只讲规则、给对照，不改识别逻辑——用户把名字和层级摆对，重扫就能认。
    """

    def __init__(self, plans: list[RenamePlan] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("认不出的 m4s 怎么改名")
        self.setMinimumSize(660, 560)
        self.plans = list(plans or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(12)

        title = QLabel("按 Steam 的形状摆好，就能认出来")
        title.setProperty("role", "pageTitle")
        title.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(hint(naming.ONE_LINER))

        # 目标形状：两列渲染，注释不会因为中英文宽度不一致而错位
        lay.addSpacing(2)
        lay.addWidget(section("一条剪辑应该长这样"))
        box = QWidget()
        box.setObjectName("namingTree")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setStyleSheet("QWidget#namingTree { background: %s; border-radius: 8px; }"
                          % theme.current().fill)
        tg = QGridLayout(box)
        tg.setContentsMargins(14, 12, 14, 12)
        tg.setHorizontalSpacing(18)
        tg.setVerticalSpacing(3)
        mono = ("font-family: Consolas, 'Cascadia Mono', 'Courier New', monospace;"
                " font-size: 12px;")
        for i, (path, note) in enumerate(naming.TREE_ROWS):
            a = QLabel(path)
            a.setStyleSheet(mono)
            tg.addWidget(a, i, 0)
            if note:
                b = QLabel(note)
                b.setStyleSheet("font-size:12px; color:%s;" % theme.current().text_2)
                tg.addWidget(b, i, 1)
        tg.setColumnStretch(1, 1)
        lay.addWidget(box)

        # 现有目录的对照（放在要点之前：用户最想先看「我这个目录怎么改」）
        for plan in self.plans:
            lay.addSpacing(6)
            head = plan.folder.name if len(self.plans) == 1 else str(plan.folder)
            lay.addWidget(section("这个目录里的分片，可以这样改" if len(self.plans) == 1
                                  else head))
            path = QLabel(str(plan.folder))
            path.setProperty("role", "meta")
            path.setWordWrap(True)
            path.setStyleSheet("font-size:11.5px;")
            lay.addWidget(path)
            if plan.rows:
                inner = QGridLayout()
                inner.setHorizontalSpacing(10)
                inner.setVerticalSpacing(5)
                now = QLabel("现在")
                now.setProperty("role", "meta")
                after = QLabel("改成")
                after.setProperty("role", "meta")
                inner.addWidget(now, 0, 0)
                inner.addWidget(after, 0, 2)
                for i, (a, b) in enumerate(plan.rows, 1):
                    old = QLabel(a)
                    old.setStyleSheet("font-family: Consolas, monospace; font-size:12px;")
                    new = QLabel(b)
                    new.setStyleSheet("font-family: Consolas, monospace; font-size:12px;"
                                      " color:%s;" % theme.current().accent)
                    arrow = QLabel("→")
                    arrow.setProperty("role", "dim")
                    inner.addWidget(old, i, 0)
                    inner.addWidget(arrow, i, 1)
                    inner.addWidget(new, i, 2)
                wrap = QHBoxLayout()
                wrap.setContentsMargins(0, 0, 0, 0)
                wrap.addLayout(inner)
                wrap.addStretch(1)
                lay.addLayout(wrap)
            if plan.note:
                lay.addWidget(hint(plan.note))

        # 规则表
        lay.addSpacing(6)
        lay.addWidget(section("要点"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for i, (what, why) in enumerate(naming.RULES):
            a = QLabel(what)
            a.setStyleSheet("font-weight:600;")
            b = QLabel(why)
            b.setProperty("role", "meta")
            b.setWordWrap(True)
            grid.addWidget(a, i, 0, Qt.AlignTop)
            grid.addWidget(b, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        if not self.plans:
            lay.addSpacing(4)
            lay.addWidget(hint("改完名字后回到主界面点「刷新」即可，不需要重启程序。"))

        lay.addStretch(1)
        root.addWidget(scroll, 1)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:%s;" % theme.current().line)
        root.addWidget(sep)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(26, 8, 26, 16)
        fl.setSpacing(8)
        self.btn_copy = QPushButton("复制做法")
        self.btn_copy.setProperty("ghost", True)
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy)
        fl.addWidget(self.btn_copy)
        if self.plans:
            self.btn_open = QPushButton("打开所在文件夹")
            self.btn_open.setProperty("ghost", True)
            self.btn_open.setCursor(Qt.PointingHandCursor)
            self.btn_open.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.plans[0].folder))))
            fl.addWidget(self.btn_open)
        fl.addStretch(1)
        ok = QPushButton("知道了")
        ok.setProperty("accent", True)
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        fl.addWidget(ok)
        root.addWidget(foot)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(naming.clipboard_text(self.plans))
        self.btn_copy.setText("已复制")
        self.btn_copy.setEnabled(False)


class RenameDialog(QDialog):
    """手动给输出文件起名：名称 + 可选时间戳。

    只改**输出文件名**，剪辑目录一个字节都不动（原目录是只读的）。
    多选时一次改一批：名称共用，时间戳各取各自剪辑封面的时间，
    例如 `影之刃零 - 2026-11-22 23-46-00.mp4`。
    """

    MAX_PREVIEW = 4

    def __init__(self, recs: list, with_stamp: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.recs = list(recs)
        self.restore = False              # 用户点了「用回文件夹名」
        n = len(self.recs)
        self.setWindowTitle("重命名" if n == 1 else f"重命名 {n} 条")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(10)

        title = QLabel("重命名输出文件")
        title.setProperty("role", "pageTitle")
        root.addWidget(title)
        root.addWidget(hint(naming.RENAME_HINT))

        # 名称：多选时若名字都一样就带出来，否则留空让用户输
        base = ""
        if self.recs:
            first = self.recs[0].out_stem
            base = first if all(r.out_stem == first for r in self.recs) else ""
        self.name_edit = QLineEdit(base)
        self.name_edit.setPlaceholderText("例如：影之刃零")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.textChanged.connect(self._refresh_preview)
        root.addWidget(self.name_edit)

        # 时间戳：格式固定，勾了就拼在名称后面
        self.stamp = QCheckBox("加上时间戳")
        self.stamp.setChecked(bool(with_stamp))
        self.stamp.toggled.connect(self._refresh_preview)
        root.addWidget(self.stamp)

        root.addSpacing(2)
        lab = QLabel("预览")
        lab.setProperty("role", "meta")
        root.addWidget(lab)
        self.preview = QWidget()
        self.preview.setObjectName("renamePreview")
        self.preview.setAttribute(Qt.WA_StyledBackground, True)
        self.preview.setStyleSheet("QWidget#renamePreview { background: %s; border-radius: 8px; }"
                                   % theme.current().fill)
        self.pl = QVBoxLayout(self.preview)
        self.pl.setContentsMargins(14, 10, 14, 10)
        self.pl.setSpacing(4)
        root.addWidget(self.preview)

        self.stamp_hint = hint("")
        root.addWidget(self.stamp_hint)

        root.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_restore = QPushButton("用回文件夹名")
        self.btn_restore.setProperty("ghost", True)
        self.btn_restore.setCursor(Qt.PointingHandCursor)
        self.btn_restore.clicked.connect(self._do_restore)
        row.addWidget(self.btn_restore)
        row.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setProperty("ghost", True)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("保存")
        self.btn_ok.setProperty("accent", True)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        for b in (self.btn_cancel, self.btn_ok):
            b.setMinimumWidth(88)
            row.addWidget(b)
        root.addLayout(row)

        self._refresh_preview()

    # ---------- 预览 ----------
    def _refresh_preview(self) -> None:
        base = self.name_edit.text().strip()
        stamp = self.stamp.isChecked()
        self.btn_ok.setEnabled(bool(base))
        # 与导出走同一套命名规则：预览里带 -2 的，导出就是 -2
        planned = (naming.plan_out_names(self.recs, base, stamp)
                   if base and self.recs else {})

        # 每行一个结果：多选时能一眼看出「共用名称、各用各自时间」
        while self.pl.count():
            it = self.pl.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        # 按时间排：最早的一条拿原名，后面的才带 -2，读起来符合直觉
        ordered = sorted(self.recs, key=lambda r: (naming.rec_stamp(r), r.title))
        for rec in ordered[:self.MAX_PREVIEW]:
            name = planned.get(rec.key, "")
            lb = ElidedLabel(f"{name}.mp4" if name else "—")
            lb.setStyleSheet("font-size:12px; color:%s;" %
                             (theme.current().text if base else theme.current().text_3))
            lb.setFixedWidth(470)
            self.pl.addWidget(lb)
        if len(self.recs) > self.MAX_PREVIEW:
            more = QLabel("… 其余 %d 条同样规则" % (len(self.recs) - self.MAX_PREVIEW))
            more.setProperty("role", "meta")
            more.setStyleSheet("font-size:11.5px;")
            self.pl.addWidget(more)
        self.preview.setVisible(bool(self.recs))

        if stamp and base:
            self.stamp_hint.setText("时间取这条剪辑 thumbnail.jpg 的文件时间；同一批多选，各用各自的时间。")
        elif stamp:
            self.stamp_hint.setText("时间取这条剪辑 thumbnail.jpg 的文件时间，格式 2026-11-22 23-46-00。")
        else:
            self.stamp_hint.setText("不勾时间戳就只用上面的名称；重名时自动加 -2、-3。")

    def _do_restore(self) -> None:
        self.restore = True
        self.accept()

    def values(self) -> tuple[str, bool]:
        return self.name_edit.text().strip(), self.stamp.isChecked()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(580)
        self.settings = settings

        # 内容比一屏高：套一层滚动区，按钮固定在底部，小屏笔记本也能操作
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(14)

        title = QLabel("设置")
        title.setProperty("role", "pageTitle")
        lay.addWidget(title)

        # FFmpeg
        lay.addSpacing(2)
        lay.addWidget(section("FFmpeg"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.ffmpeg_edit = QLineEdit(settings.get("ffmpeg_dir", ""))
        self.ffmpeg_edit.setPlaceholderText("留空自动探测：PATH / 程序目录 / bin")
        b = QPushButton("选择")
        b.setProperty("ghost", True)
        b.setFixedWidth(64)
        row.addWidget(self.ffmpeg_edit, 1)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(hint("合并本身不需要转码，但直通失败时会用 ffmpeg 重编码兜底，"
                           "所以必须有。"))

        # 导出
        lay.addSpacing(4)
        lay.addWidget(section("导出"))
        orow = QHBoxLayout()
        orow.setSpacing(6)
        self.out_edit = QLineEdit(settings.get("output_dir", "") or str(default_output_dir()))
        ob = QPushButton("选择")
        ob.setProperty("ghost", True)
        ob.setFixedWidth(64)
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(ob)
        lay.addLayout(orow)
        lay.addWidget(hint("合并出的 mp4 放这里。文件名沿用剪辑文件夹名（可手动改），"
                           "同名时自动加 -2、-3，不覆盖。"))

        # 剪辑目录
        lay.addSpacing(4)
        lay.addWidget(section("剪辑目录"))
        self.roots = _HintList("暂无自定义目录 · Steam 的 clips 目录会自动探测")
        self.roots.setFixedHeight(88)
        self.roots.setFrameShape(QFrame.NoFrame)
        for r in settings.get("scan_roots", []):
            self.roots.addItem(r)
        lay.addWidget(self.roots)
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        add = QPushButton("添加")
        add.setProperty("ghost", True)
        rm = QPushButton("移除")
        rm.setProperty("ghost", True)
        r2.addWidget(add)
        r2.addWidget(rm)
        r2.addWidget(hint("Steam 的剪辑目录会自动探测；这里只加额外的位置"), 1)
        lay.addLayout(r2)

        # 行为
        lay.addSpacing(4)
        lay.addWidget(section("行为"))
        self.auto_scan = QCheckBox("启动时自动扫描")
        self.auto_scan.setChecked(bool(settings.get("auto_scan_on_start", True)))
        lay.addWidget(self.auto_scan)

        # 临时文件：固定程序目录 temp、退出即删（不提供修改入口）
        lay.addSpacing(6)
        lay.addWidget(section("临时文件"))
        fixed = QLineEdit(str(app_temp_dir()))
        fixed.setReadOnly(True)
        fixed.setFocusPolicy(Qt.NoFocus)
        fixed.setStyleSheet("color:#8a8f98;")
        lay.addWidget(fixed)
        lay.addWidget(hint("合并的中间片只放在这里，不写剪辑目录；导出结束或退出程序时立刻删除。"
                           "位置固定不可改，避免中间片散落到 C 盘或回放目录。"))

        lay.addStretch(1)
        root.addWidget(scroll, 1)
        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(24, 8, 24, 16)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText("保存")
        ok.setProperty("accent", True)
        cancel = buttons.button(QDialogButtonBox.Cancel)
        cancel.setText("取消")
        cancel.setProperty("ghost", True)
        fl.addWidget(buttons)
        root.addWidget(foot)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        b.clicked.connect(lambda: self._pick_dir(self.ffmpeg_edit))
        ob.clicked.connect(lambda: self._pick_dir(self.out_edit))
        add.clicked.connect(lambda: self._pick_dir(self.roots, as_list=True))
        rm.clicked.connect(self._remove_root)

    def _pick_dir(self, target, as_list: bool = False) -> None:
        start = target.text() if not as_list else ""
        d = QFileDialog.getExistingDirectory(self, "选择目录", start or "")
        if not d:
            return
        if as_list:
            self.roots.addItem(d)
        else:
            target.setText(d)

    def _remove_root(self) -> None:
        for it in self.roots.selectedItems():
            self.roots.takeItem(self.roots.row(it))

    def apply(self) -> None:
        self.settings.set("ffmpeg_dir", self.ffmpeg_edit.text().strip())
        out = self.out_edit.text().strip()
        # 路径不存在时退回默认，避免导出时才发现目录没了
        self.settings.set("output_dir", out if out and Path(out).is_dir() else "")
        self.settings.set("scan_roots",
                          [self.roots.item(i).text() for i in range(self.roots.count())])
        self.settings.set("auto_scan_on_start", self.auto_scan.isChecked())
        self.settings.save()
