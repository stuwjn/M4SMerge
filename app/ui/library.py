"""剪辑列表页。

一行一条剪辑：复选框、封面、名称、体积/时长/时间、单条导出按钮。
右键（或 F2）可以手动改输出文件名，勾上时间戳就得到
「影之刃零 - 2026-11-22 23-46-00.mp4」；剪辑目录本身不动。
所有耗时动作（扫描、读封面）都不在 GUI 线程里做；封面按「一次一张 +
让出事件循环」的节奏加载，几百条也不会卡住界面。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..core.naming import stamp_text
from ..core.recording import Recording
from ..core.utils import human_duration
from . import theme
from .widgets import CoverLabel, ElidedLabel, bold

ROLE_REC = Qt.UserRole + 1
ROW_H = 78
COVER = QSize(96, 54)
BATCH = 30          # 每轮插入多少行（兼顾首屏速度与单次阻塞）


def _apply(w, css: str) -> None:
    if w.styleSheet() != css:
        w.setStyleSheet(css)


class _TriCheck(QCheckBox):
    """三态复选框，但**点击只在「全选 / 全不选」之间切换**。

    QCheckBox 自带的三态点击顺序是 未选 → 半选 → 全选 → 未选，
    点一下只到半选，用户会以为没生效。半选在这里只作状态显示，
    由程序按实际勾选数量设置。
    """

    def nextCheckState(self) -> None:  # noqa: N802
        self.setCheckState(Qt.Unchecked if self.checkState() == Qt.Checked else Qt.Checked)


class RecordingRow(QWidget):
    """单行：☐ + 封面 96×54 + 名称/元信息 + 时长 + 导出按钮。"""

    toggled = Signal(str, bool)      # key, checked
    exportOne = Signal(str)          # key
    clickedRow = Signal(str)         # key（只负责高亮，不做动作）
    menuRequested = Signal(str, object)   # key, 全局坐标（右键）

    def __init__(self, rec: Recording, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = rec.key
        self.rec = rec
        self._active = False
        self._hover = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 12, 10)
        lay.setSpacing(14)

        self.check = QCheckBox()
        self.check.setCursor(Qt.PointingHandCursor)
        self.check.setToolTip("勾选后可批量导出")
        self.check.toggled.connect(lambda on: self.toggled.emit(self.key, on))
        lay.addWidget(self.check, 0, Qt.AlignVCenter)

        self.cover = CoverLabel(COVER, radius=7)
        lay.addWidget(self.cover, 0, Qt.AlignVCenter)

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.title = ElidedLabel(rec.out_stem)
        bold(self.title, 15)
        self.meta = ElidedLabel(rec.subtitle)
        self.meta.setProperty("role", "meta")
        box.addWidget(self.title)
        box.addWidget(self.meta)
        lay.addLayout(box, 1)

        self.dur = QLabel(human_duration(rec.duration) if rec.duration else "--:--")
        self.dur.setProperty("role", "dur")
        self.dur.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.dur.setFixedWidth(56)
        lay.addWidget(self.dur, 0, Qt.AlignVCenter)

        self.btn = QPushButton("导出")
        self.btn.setProperty("rowAction", True)
        self.btn.setCursor(Qt.PointingHandCursor)
        # 宽 84 是「导出」两个字（30px）+ 左右各 18px 内边距 + 余量，再窄字就被压
        self.btn.setMinimumWidth(84)
        self.btn.setFixedHeight(38)
        self.btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn.setFocusPolicy(Qt.NoFocus)
        self.btn.clicked.connect(lambda: self.exportOne.emit(self.key))
        lay.addWidget(self.btn, 0, Qt.AlignVCenter)

        self.refresh_tooltip()

    # ---------- 名称 ----------
    def refresh_tooltip(self) -> None:
        tips = [str(self.rec.path)]
        if self.rec.out_title:
            tips.insert(0, f"原文件夹名：{self.rec.title}")
        if self.rec.warnings:
            tips.append("；".join(self.rec.warnings))
        if self.rec.appid:
            tips.insert(0, f"AppID {self.rec.appid}")
        if self.rec.stamp:
            tips.append(f"封面时间：{stamp_text(self.rec.stamp)}（打时间戳用这个）")
        self.setToolTip("\n".join(tips))

    def set_display_name(self, name: str) -> None:
        """改过的名字立刻显示出来（不用重建整张列表）。"""
        self.title.setText(name)
        self.refresh_tooltip()

    # ---------- 封面 ----------
    def set_cover(self, pm: QPixmap) -> None:
        self.cover.set_pixmap(pm)

    # ---------- 选中态 ----------
    def set_checked(self, on: bool) -> None:
        if self.check.isChecked() != on:
            self.check.blockSignals(True)
            self.check.setChecked(on)
            self.check.blockSignals(False)

    def is_checked(self) -> bool:
        return self.check.isChecked()

    def set_active(self, on: bool) -> None:
        """选中行：蓝底 + 蓝字（沿用原项目的 .track.playing 处理）。"""
        if self._active == on:
            return
        self._active = on
        t = theme.current()
        color = t.accent if on else t.text
        _apply(self.title, f"color:{color};")
        _apply(self.meta, f"color:{t.accent if on else t.text_2};")
        _apply(self.dur, f"color:{color};")
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        if self._active or self._hover:
            t = theme.current()
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent_soft if self._active else t.surface_2))
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 12, 12)
            p.end()

    def enterEvent(self, ev) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.clickedRow.emit(self.key)
        super().mousePressEvent(ev)

    def contextMenuEvent(self, ev) -> None:  # noqa: N802
        self.menuRequested.emit(self.key, ev.globalPos())


class EmptyClipsDialog(QDialog):
    """启动扫描为空时弹这个：几条出路，明确不带歧义。

    如果扫到了 m4s 却认不出来，标题和正文会换一套说法，
    并多出一个「怎么改名」——这是本程序对非 Steam 来源的唯一出路：
    不改识别逻辑，让用户把名字与层级摆成 Steam 的样子。
    """

    REFRESH, PICK, NAMING = 1, 2, 3

    def __init__(self, parent: QWidget | None = None,
                 searched: list[str] | None = None,
                 unmatched: list | None = None) -> None:
        super().__init__(parent)
        self.unmatched = list(unmatched or [])
        self.action = 0
        found = sum(getattr(u, "m4s", 0) for u in self.unmatched)

        if self.unmatched:
            self.setWindowTitle("找到分片，但认不出来")
            self.setMinimumWidth(540)
        else:
            self.setWindowTitle("没有找到剪辑")
            self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(12)

        title = QLabel("找到 %d 个 m4s，但认不出来" % found if self.unmatched
                       else "没有找到剪辑")
        title.setProperty("role", "pageTitle")
        title.setWordWrap(True)
        lay.addWidget(title)

        body = QLabel("分片在，但文件名或目录层级和 Steam 的不一样。\n"
                      "点「怎么改名」照着改一改，回来刷新就能认；不用重启程序。"
                      if self.unmatched else
                      "Steam 里保存一段剪辑后再回来刷新；\n"
                      "如果剪辑存在别的位置，也可以手动指定文件夹。")
        body.setWordWrap(True)
        lay.addWidget(body)

        if self.unmatched:
            head = self.unmatched[0]
            where = QLabel("%s\n%s" % (head.folder, head.reason))
            where.setProperty("role", "meta")
            where.setWordWrap(True)
            where.setStyleSheet("font-size:11.5px;")
            lay.addWidget(where)
        elif searched:
            where = QLabel("已查找：\n" + "\n".join(searched[:4])
                           + ("\n…" if len(searched) > 4 else ""))
            where.setProperty("role", "meta")
            where.setWordWrap(True)
            where.setStyleSheet("font-size:11.5px;")
            lay.addWidget(where)

        lay.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setProperty("ghost", True)
        self.btn_naming = QPushButton("怎么改名")
        self.btn_naming.setProperty("ghost", True)
        self.btn_pick = QPushButton("手动选择文件夹")
        self.btn_pick.setProperty("ghost", True)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setProperty("accent", True)
        self.btn_naming.setVisible(bool(self.unmatched))
        for b in (self.btn_cancel, self.btn_naming, self.btn_pick, self.btn_refresh):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(96)
            row.addWidget(b)
        lay.addLayout(row)

        self.btn_refresh.clicked.connect(lambda: self._done(self.REFRESH))
        self.btn_pick.clicked.connect(lambda: self._done(self.PICK))
        self.btn_naming.clicked.connect(lambda: self._done(self.NAMING))
        self.btn_cancel.clicked.connect(lambda: self._done(0))

    def _done(self, action: int) -> None:
        self.action = action
        self.accept() if action else self.reject()


class LibraryPage(QWidget):
    exportRequested = Signal(object)          # Recording
    exportManyRequested = Signal(list)        # list[Recording]
    scanRequested = Signal()
    pickFolderRequested = Signal()
    namingHelpRequested = Signal()            # 有 m4s 认不出时，用户点了「怎么改名」
    renameRequested = Signal(list)            # list[Recording]，手动改输出名

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all: list[Recording] = []
        self._unmatched: list = []
        self._items: dict[str, QListWidgetItem] = {}
        self._rows: dict[str, RecordingRow] = {}
        self._query = ""
        self._checked: set[str] = set()   # 勾选状态唯一真相：换排序、搜索都不会丢
        self._gen = 0                     # 列表重建代际
        self._pending: list[Recording] = []
        self._cur_key: str | None = None
        self._cover_idx = 0
        self._cover_budget = 0        # 每轮事件循环加载几张
        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(160)
        self._query_timer.timeout.connect(self.refresh)
        self._build()

    # ---------- UI ----------
    def _build(self) -> None:
        self._lay = lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 10)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 12, 0)     # 右边留 12，和批量条、行内按钮右边界对齐
        head.setSpacing(10)
        self.title = QLabel("剪辑")
        self.title.setProperty("role", "h1")
        self.count = QLabel("0 个")
        self.count.setProperty("role", "muted")
        self.count.setContentsMargins(8, 0, 0, 7)
        # 有分片认不出时，标题右边挂一个小提醒，点开看命名规则
        self.naming_hint = QPushButton()
        self.naming_hint.setProperty("link", True)
        self.naming_hint.setCursor(Qt.PointingHandCursor)
        self.naming_hint.setVisible(False)
        self.naming_hint.clicked.connect(self.namingHelpRequested.emit)
        head.addWidget(self.title)
        head.addWidget(self.count, 0, Qt.AlignBottom)
        head.addWidget(self.naming_hint, 0, Qt.AlignBottom)
        head.addStretch(1)

        self.sort = QComboBox()
        self.sort.addItems(["最新优先", "时长最长", "体积最大", "名称"])
        # 112 时文字和箭头正好贴死；给到 132 才有余量（文字 56 + 箭头 11 + 内边距）
        self.sort.setMinimumWidth(132)
        self.sort.setFixedHeight(38)
        self.sort.setCursor(Qt.PointingHandCursor)
        self.sort.currentIndexChanged.connect(lambda _: self.refresh())
        head.addWidget(self.sort)

        self.btn_pick = QPushButton("手动选择文件夹")
        self.btn_pick.setProperty("ghost", True)
        self.btn_pick.setFixedHeight(38)
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.clicked.connect(self.pickFolderRequested.emit)
        head.addWidget(self.btn_pick)

        self.btn_scan = QPushButton("⟳  刷新")
        self.btn_scan.setProperty("ghost", True)
        self.btn_scan.setFixedHeight(38)
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self.scanRequested.emit)
        head.addWidget(self.btn_scan)
        lay.addLayout(head)

        # 批量条（空列表时整条隐藏，省得摆一堆点不动的按钮）
        self.bulk = QWidget()
        bar = QHBoxLayout(self.bulk)
        bar.setSpacing(10)
        bar.setContentsMargins(12, 10, 12, 10)
        self.check_all = _TriCheck("全选")
        self.check_all.setCursor(Qt.PointingHandCursor)
        self.check_all.setTristate(True)
        self.check_all.clicked.connect(self._on_check_all)
        bar.addWidget(self.check_all)
        self.sel_info = QLabel("未选择")
        self.sel_info.setProperty("role", "meta")
        bar.addWidget(self.sel_info)
        bar.addStretch(1)
        self.btn_rename = QPushButton("重命名")
        self.btn_rename.setProperty("ghost", True)
        self.btn_rename.setCursor(Qt.PointingHandCursor)
        self.btn_rename.setFixedHeight(38)
        self.btn_rename.setEnabled(False)
        self.btn_rename.setToolTip("改导出文件的名字（可加时间戳）")
        self.btn_rename.clicked.connect(lambda: self.renameRequested.emit(self.selected()))
        bar.addWidget(self.btn_rename)
        self.btn_export_sel = QPushButton("导出所选")
        self.btn_export_sel.setProperty("accent", True)
        self.btn_export_sel.setCursor(Qt.PointingHandCursor)
        self.btn_export_sel.setFixedHeight(38)
        self.btn_export_sel.setEnabled(False)
        self.btn_export_sel.clicked.connect(self._emit_many)
        bar.addWidget(self.btn_export_sel)
        lay.addWidget(self.bulk)

        self.list = QListWidget()
        self.list.setSpacing(0)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setFrameShape(QListWidget.NoFrame)
        self.list.setViewportMargins(-8, 0, 0, 0)
        self.list.currentItemChanged.connect(
            lambda cur, _p: self._sync_active() if cur else None)
        lay.addWidget(self.list, 1)

        # 空状态
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 60, 0, 0)
        ev.setSpacing(10)
        ev.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.empty_title = QLabel("还没有剪辑")
        self.empty_title.setProperty("role", "h2")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_body = QLabel("在 Steam 里保存一段剪辑后点「刷新」\n"
                                 "也可以手动指定剪辑所在的文件夹")
        self.empty_body.setProperty("role", "dim")
        self.empty_body.setAlignment(Qt.AlignCenter)
        self.empty_btn = QPushButton("刷新")
        self.empty_btn.setProperty("accent", True)
        self.empty_btn.setCursor(Qt.PointingHandCursor)
        self.empty_btn.setFixedWidth(120)
        self.empty_btn.clicked.connect(self.scanRequested.emit)
        self.empty_pick = QPushButton("手动选择文件夹")
        self.empty_pick.setProperty("ghost", True)
        self.empty_pick.setCursor(Qt.PointingHandCursor)
        self.empty_pick.setFixedWidth(140)
        self.empty_pick.clicked.connect(self.pickFolderRequested.emit)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(self.empty_btn)
        row.addWidget(self.empty_pick)
        row.addStretch(1)
        ev.addWidget(self.empty_title)
        ev.addWidget(self.empty_body)
        ev.addSpacing(6)
        ev.addLayout(row)
        self.empty.hide()
        lay.addWidget(self.empty, 1)
        self.refresh()          # 初始无数据时也要把空状态摆上来

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        pad = max(24, int(self.width() * 0.04))
        self._lay.setContentsMargins(pad, 24, pad, 10)

    # ---------- 数据 ----------
    def set_recordings(self, recs: list[Recording]) -> None:
        self._all = list(recs)
        self.count.setText(f"{len(recs)} 个")
        alive = {r.key for r in recs}
        self._checked &= alive          # 已经不在列表里的条目顺手清掉
        self.check_all.setChecked(False)
        self.refresh()

    def recordings(self) -> list[Recording]:
        return list(self._all)

    def set_unmatched(self, dirs: list) -> None:
        """记下「有 m4s 但认不出」的目录，挂一条提醒（不改识别逻辑）。"""
        self._unmatched = list(dirs or [])
        n = sum(getattr(u, "m4s", 0) for u in self._unmatched)
        self.naming_hint.setVisible(n > 0)
        if n:
            self.naming_hint.setText("%d 个 m4s 未识别 · 怎么改名" % n)
            self.naming_hint.setToolTip("按 Steam 的文件名与目录层级摆好，重新扫描就能认出来")

    def unmatched(self) -> list:
        return list(self._unmatched)

    def set_query(self, text: str) -> None:
        q = (text or "").strip().lower()
        if q == self._query:
            return
        self._query = q
        self._query_timer.start()      # 防抖：连续敲字只在停顿后重建一次

    def selected(self) -> list[Recording]:
        return [r for r in self._all if r.key in self._checked]

    def current(self) -> Recording | None:
        it = self.list.currentItem()
        return it.data(ROLE_REC) if it else None

    # ---------- 重建 ----------
    def refresh(self) -> None:
        recs = [r for r in self._all if self._match(r)]
        mode = self.sort.currentIndex()
        if mode == 0:
            recs.sort(key=lambda r: r.mtime, reverse=True)
        elif mode == 1:
            recs.sort(key=lambda r: r.duration, reverse=True)
        elif mode == 2:
            recs.sort(key=lambda r: r.size, reverse=True)
        else:
            recs.sort(key=lambda r: r.out_stem.lower())

        cur = self.current()
        self._cur_key = cur.key if cur else None
        self._gen += 1                   # 代际：分批插入途中又刷新时，旧批次作废
        self._pending = recs

        has = bool(recs)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.bulk.setVisible(bool(self._all))
        self.sort.setVisible(bool(self._all))
        if not self._all:
            self.empty_title.setText("还没有剪辑")
            self.empty_body.setText("在 Steam 里保存一段剪辑后点「刷新」\n"
                                    "也可以手动指定剪辑所在的文件夹")
        elif not recs:
            self.empty_title.setText("没有匹配的结果")
            self.empty_body.setText("换个关键词试试")

        # 几百行一次性插入会让界面停半秒；改成每轮 30 行，首屏立刻出现
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        self._items.clear()
        self._rows.clear()
        self._build_batch(self._gen)

    def _build_batch(self, gen: int) -> None:
        if gen != self._gen:
            return                        # 期间又刷新了，这批丢掉
        batch, self._pending = self._pending[:BATCH], self._pending[BATCH:]
        for rec in batch:
            it = QListWidgetItem()
            it.setData(ROLE_REC, rec)
            it.setSizeHint(QSize(0, ROW_H))
            self.list.addItem(it)
            row = RecordingRow(rec, self.list)
            row.toggled.connect(self._on_row_toggled)
            row.exportOne.connect(self._on_export_one)
            row.clickedRow.connect(self._on_row_clicked)
            row.menuRequested.connect(self._on_row_menu)
            row.set_checked(rec.key in self._checked)
            self.list.setItemWidget(it, row)
            self._items[rec.key] = it
            self._rows[rec.key] = row
            if rec.key == self._cur_key:
                self.list.setCurrentItem(it)
        if self._pending:
            QTimer.singleShot(0, lambda: self._build_batch(gen))
            return
        self._finish_refresh(gen)

    def _finish_refresh(self, gen: int) -> None:
        if gen != self._gen:
            return
        self.list.setUpdatesEnabled(True)
        self._sync_active()
        self._sync_selection()
        self._cover_idx = 0
        QTimer.singleShot(0, self._load_covers)

    def refresh_active(self) -> None:
        """主题切换后重新着色（行内颜色是内联样式，不会自动跟随 QSS）。"""
        self._sync_active()
        self.update()

    def _match(self, rec: Recording) -> bool:
        if not self._query:
            return True
        return self._query in f"{rec.title} {rec.path} {rec.appid}".lower()

    # ---------- 封面：一次一张，让出事件循环 ----------
    def _load_covers(self) -> None:
        keys = list(self._rows)
        if self._cover_idx >= len(keys):
            return
        # 每轮最多 3 张：读图按毫秒算，3 张仍是「眨眼级」，但足够让输入事件插进来
        for _ in range(3):
            if self._cover_idx >= len(keys):
                break
            key = keys[self._cover_idx]
            self._cover_idx += 1
            row = self._rows.get(key)
            if row is None:
                continue
            rec = row.rec
            if rec.thumb is None:
                continue
            reader = QImageReader(str(rec.thumb))
            reader.setAutoTransform(True)
            # 解码时就缩到 2 倍显示尺寸：大图能快一个数量级
            reader.setScaledSize(QSize(COVER.width() * 2, COVER.height() * 2))
            img = reader.read()
            if img.isNull():
                continue
            row.set_cover(QPixmap.fromImage(img))
        QTimer.singleShot(0, self._load_covers)

    # ---------- 选择 ----------
    def _on_row_toggled(self, key: str, on: bool) -> None:
        if on:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self._sync_selection()

    def _on_row_clicked(self, key: str) -> None:
        it = self._items.get(key)
        if it is not None and self.list.currentItem() is not it:
            self.list.setCurrentItem(it)

    # ---------- 重命名 ----------
    def _rec_by_key(self, key: str) -> Recording | None:
        for r in self._all:
            if r.key == key:
                return r
        return None

    def _on_row_menu(self, key: str, pos) -> None:
        """右键：勾了多条就改这一批，否则只改点中的那一条。"""
        rec = self._rec_by_key(key)
        if rec is None:
            return
        targets = self.rename_targets(key)
        menu = QMenu(self)
        act_rename = menu.addAction("重命名…")
        act_rename.setEnabled(bool(targets))
        menu.addSeparator()
        act_export = menu.addAction("导出这一条")
        chosen = menu.exec(pos)
        if chosen is act_rename:
            self.renameRequested.emit(targets)
        elif chosen is act_export:
            self.exportOne.emit(key)

    def rename_targets(self, key: str | None = None) -> list[Recording]:
        """要改名的对象：这一条已被勾选、且勾了不止一条时，改整批。"""
        if key:
            rec = self._rec_by_key(key)
            if rec is None:
                return []
            if key in self._checked and len(self._checked) > 1:
                return self.selected()
            return [rec]
        cur = self.current()
        if cur is not None:
            if cur.key in self._checked and len(self._checked) > 1:
                return self.selected()
            return [cur]
        return self.selected()

    def refresh_names(self) -> None:
        """重命名之后只换文字，不重建列表（勾选状态、滚动位置都不动）。"""
        for key, row in self._rows.items():
            row.set_display_name(row.rec.out_stem)
        for rec in self._all:
            it = self._items.get(rec.key)
            if it is not None:
                it.setData(ROLE_REC, rec)

    def _on_check_all(self) -> None:
        """全选只作用于**当前可见**的行：搜索后点全选，选中的是搜出来的这些。"""
        on = self.check_all.checkState() != Qt.Unchecked
        for key, row in self._rows.items():
            row.set_checked(on)
            if on:
                self._checked.add(key)
            else:
                self._checked.discard(key)
        self._sync_selection()

    def _sync_selection(self) -> None:
        visible = list(self._rows)
        total = len(visible)
        shown_on = sum(1 for k in visible if k in self._checked)
        n = len(self._checked)          # 含被搜索隐藏的条目
        self.sel_info.setText(f"已选 {n} 项" if n else "未选择")
        self.btn_export_sel.setEnabled(n > 0)
        self.btn_export_sel.setText(f"导出所选（{n}）" if n else "导出所选")
        self.btn_rename.setEnabled(n > 0)
        self.check_all.blockSignals(True)
        if shown_on == 0:
            self.check_all.setCheckState(Qt.Unchecked)
        elif shown_on == total:
            self.check_all.setCheckState(Qt.Checked)
        else:
            self.check_all.setCheckState(Qt.PartiallyChecked)
        self.check_all.blockSignals(False)
        self.check_all.setEnabled(total > 0)

    def _sync_active(self) -> None:
        cur = self.list.currentItem()
        for key, row in self._rows.items():
            it = self._items.get(key)
            row.set_active(it is not None and it is cur)

    # ---------- 导出 ----------
    def _on_export_one(self, key: str) -> None:
        for rec in self._all:
            if rec.key == key:
                self.exportRequested.emit(rec)
                return

    def _emit_many(self) -> None:
        recs = self.selected()
        if recs:
            self.exportManyRequested.emit(recs)

    def set_checked_all(self, on: bool) -> None:
        for key, row in self._rows.items():
            row.set_checked(on)
            if on:
                self._checked.add(key)
            else:
                self._checked.discard(key)
        self._sync_selection()
