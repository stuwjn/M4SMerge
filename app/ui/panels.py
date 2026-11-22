"""导出队列页面。"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.export import ExportJob, Exporter
from . import theme


class QueueRunner(QThread):
    """顺序跑队列：一次只开一个 ffmpeg，磁盘和 CPU 都不会被抢爆。"""

    jobUpdated = Signal(int)
    finishedAll = Signal()

    def __init__(self, exporter: Exporter, jobs: list[ExportJob], parent=None) -> None:
        super().__init__(parent)
        self.exporter = exporter
        self.jobs = jobs

    def run(self) -> None:
        for i, job in enumerate(self.jobs):
            if job.status != "pending":
                continue
            self.jobUpdated.emit(i)
            self.exporter.run_job(
                job, on_progress=lambda p, m, idx=i: self.jobUpdated.emit(idx))
            self.jobUpdated.emit(i)
        self.finishedAll.emit()


class QueuePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.jobs: list[ExportJob] = []
        self._lay = lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 12)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("导出队列")
        title.setProperty("role", "h1")
        self.count = QLabel("0 个任务")
        self.count.setProperty("role", "muted")
        self.count.setContentsMargins(8, 0, 0, 7)
        head.addWidget(title)
        head.addWidget(self.count, 0, Qt.AlignBottom)
        head.addStretch(1)
        self.btn_cancel = QPushButton("取消当前")
        self.btn_cancel.setProperty("ghost", True)
        self.btn_open = QPushButton("打开输出目录")
        self.btn_open.setProperty("ghost", True)
        self.btn_clean = QPushButton("清理已完成")
        self.btn_clean.setProperty("ghost", True)
        for b in (self.btn_cancel, self.btn_open, self.btn_clean):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("padding: 8px 12px;")
            head.addWidget(b)
        lay.addLayout(head)
        lay.addSpacing(18)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件", "状态", "进度"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QTableWidget.NoFrame)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 140)
        self.table.verticalHeader().setDefaultSectionSize(44)
        hh.setFixedHeight(36)
        lay.addWidget(self.table, 1)

        self.empty = QLabel("队列是空的\n在「剪辑」页点每行右边的「导出」，或勾选多条后点「导出所选」")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setProperty("role", "dim")
        self.empty.setStyleSheet("font-size: 14px;")
        lay.addWidget(self.empty, 1)

        self.btn_cancel.clicked.connect(self.cancel_current)
        self.btn_open.clicked.connect(self.open_output_dir)
        self.btn_clean.clicked.connect(self.clean_done)
        self.table.cellDoubleClicked.connect(self._reveal_row)
        self._sync_empty()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        pad = max(24, int(self.width() * 0.04))
        self._lay.setContentsMargins(pad, 24, pad, 12)

    # ---------- 行 ----------
    def add_job(self, job: ExportJob) -> int:
        self.jobs.append(job)
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(job.out.name))
        self.table.setItem(r, 1, QTableWidgetItem("等待中"))
        self.table.setItem(r, 2, QTableWidgetItem("0%"))
        self.table.item(r, 0).setToolTip(str(job.out))
        for c in range(3):
            self.table.item(r, c).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._sync_empty()
        return len(self.jobs) - 1

    def update_row(self, index: int) -> None:
        if not (0 <= index < len(self.jobs)) or index >= self.table.rowCount():
            return
        job = self.jobs[index]
        t = theme.current()
        status = {"pending": "等待中", "running": "合并中",
                  "done": "已完成", "failed": "失败", "canceled": "已取消"}.get(
            job.status, job.status)
        self.table.item(index, 1).setText(status)
        color = {"done": t.ok, "failed": t.danger, "canceled": t.warn}.get(job.status, t.text)
        self.table.item(index, 1).setForeground(QColor(color))
        self.table.item(index, 2).setText(f"{int(round(job.progress * 100))}%")
        if job.message:
            self.table.item(index, 1).setToolTip(job.message)
        if job.status == "failed":
            self.table.item(index, 0).setToolTip(f"{job.out}\n{job.message}")
        self.count.setText(f"{len(self.jobs)} 个任务")

    def refresh_all(self) -> None:
        for i in range(len(self.jobs)):
            self.update_row(i)

    def pending_jobs(self) -> list[ExportJob]:
        return [j for j in self.jobs if j.status == "pending"]

    def _sync_empty(self) -> None:
        self.table.setVisible(bool(self.jobs))
        self.empty.setVisible(not self.jobs)
        self.count.setText(f"{len(self.jobs)} 个任务")

    # ---------- 操作 ----------
    def cancel_current(self) -> None:
        for job in self.jobs:
            if job.status == "running":
                job.cancel.set()
                break

    def open_output_dir(self) -> None:
        target = next((j.out.parent for j in reversed(self.jobs) if j.out), None)
        if target is not None and target.exists():
            open_in_explorer(target)

    def clean_done(self) -> None:
        keep = [j for j in self.jobs if j.status in ("running", "pending")]
        self.jobs = keep
        self.table.setRowCount(0)
        for j in keep:
            self.add_job(j)
        self.refresh_all()
        self._sync_empty()

    def _reveal_row(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.jobs):
            job = self.jobs[row]
            target = job.results[0] if job.results else job.out
            open_in_explorer(target.parent if target.is_file() else target)


def open_in_explorer(path: Path) -> None:
    try:
        if os.name == "nt":
            # explorer 对 /select, 以外的参数按字符串解析，路径含空格时用引号包住
            subprocess.Popen(["explorer", str(path)])
        elif platform.system() == "Darwin":   # os.uname 在 Windows 上不存在
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except (OSError, subprocess.SubprocessError):
        pass
