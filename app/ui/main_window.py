"""主窗口：顶部导航 + 两个页面（剪辑 / 导出队列）+ 右下角导出提示。

M4SMerge 只做一件事：把 Steam 保存的剪辑合并成 mp4。
所以这里没有播放器、没有时间轴、没有剪辑单——扫描、勾选、导出。
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core.export import ExportJob, Exporter, build_output_path
from ..core.ffmpeg import FFmpeg, FFmpegError
from ..core.naming import plan_for
from ..core.recording import Canceled, Preparer, Recording
from ..core.scanner import Scanner, default_scan_roots, steam_clip_dirs
from ..core.settings import APP_NAME, Settings, default_output_dir
from . import theme
from .dialogs import NamingHelpDialog, SettingsDialog
from .library import EmptyClipsDialog, LibraryPage
from .panels import QueuePage
from .toast import ToastStack
from .topbar import TopBar

PAGE_CLIPS, PAGE_QUEUE = 0, 1


class ScanWorker(QThread):
    progress = Signal(str, int)
    done = Signal(list, list)      # (认出来的剪辑, 有 m4s 但认不出的目录)
    failed = Signal(str)

    def __init__(self, ff: FFmpeg, roots: list[Path], parent=None) -> None:
        super().__init__(parent)
        self.ff = ff
        self.roots = roots
        self._stop = False

    def stop(self) -> None:
        """关窗时调用：扫描本身会跑完，但不再把结果发回已销毁的界面。"""
        self._stop = True

    def run(self) -> None:
        try:
            recs, unmatched = Scanner(self.ff).scan_ex(
                self.roots,
                on_progress=lambda p, n: self.progress.emit(p, n) if not self._stop else None)
            if not self._stop:
                self.done.emit(recs, unmatched)
        except Exception as exc:  # noqa: BLE001
            if not self._stop:
                self.failed.emit(str(exc))


class ExportRunner(QThread):
    """一条一条处理队列：拼接分片 → 封装到目标路径。

    进度合并成一条：拼接占 0–70%，封装占 70–100%，用户看到的是一根连续的条。
    没有并发——两个 ffmpeg 同时啃同一个磁盘只会互相拖慢。
    """

    jobStarted = Signal(int)
    jobProgress = Signal(int, float, str)
    jobFinished = Signal(int)
    finishedAll = Signal()

    def __init__(self, jobs: list[ExportJob], preparer: Preparer,
                 exporter: Exporter, parent=None) -> None:
        super().__init__(parent)
        self.jobs = jobs
        self.preparer = preparer
        self.exporter = exporter
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        for j in self.jobs:
            if j.status == "running":
                j.cancel.set()

    def run(self) -> None:
        for i, job in enumerate(self.jobs):
            if self._stop or job.status != "pending":
                continue
            rec = job.rec
            self.jobStarted.emit(i)
            if rec is None:
                job.status, job.message = "failed", "剪辑信息丢失，请刷新后重试"
                self.jobFinished.emit(i)
                continue
            try:
                info = self.preparer.prepare(
                    rec,
                    progress=lambda p, m, idx=i: self.jobProgress.emit(idx, p * 0.7, m),
                    cancel=job.cancel)
                job.src = rec.prepared
                job.duration = info.duration or job.duration
                self.exporter.run_job(
                    job,
                    on_progress=lambda p, m, idx=i: self.jobProgress.emit(
                        idx, 0.7 + p * 0.3, m))
            except Canceled:
                job.status, job.message = "canceled", "已取消"
            except (FFmpegError, OSError) as exc:
                job.status, job.message = "failed", str(exc)
            except Exception as exc:  # noqa: BLE001
                job.status, job.message = "failed", f"未知错误：{exc}"
            finally:
                self.jobFinished.emit(i)
        self.finishedAll.emit()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.ff = FFmpeg(settings.get("ffmpeg_dir", ""))
        self.preparer = Preparer(self.ff, settings.get("temp_dir", ""))
        self.exporter = Exporter(self.ff, settings.get("temp_dir", ""))
        self.scanner = Scanner(self.ff)
        self._scan_worker: ScanWorker | None = None
        self._runner: ExportRunner | None = None
        self._runner_idx: dict[int, int] = {}      # runner 下标 -> queue 下标
        self._empty_shown = False
        self._unmatched: list = []                 # 有 m4s 却认不出的目录

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 760)
        self.setMinimumSize(900, 580)
        self._build()
        self._wire()
        self.topbar.set_theme_icon(theme.current().mode)
        self._update_ffmpeg_banner()

        if self.settings.get("auto_scan_on_start", True):
            QTimer.singleShot(180, lambda: self.start_scan(announce=True))

    # ---------------- UI ----------------
    def _build(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.topbar = TopBar(["剪辑", "导出队列"])
        root.addWidget(self.topbar)

        self.banner = QPushButton("未找到 FFmpeg，点这里指定路径（否则无法合并）")
        self.banner.setCursor(Qt.PointingHandCursor)
        self._style_banner()
        self.banner.clicked.connect(self.open_settings)
        self.banner.hide()
        root.addWidget(self.banner)

        self.pages = QStackedWidget()
        self.library = LibraryPage()
        self.queue = QueuePage()
        self.pages.addWidget(self.library)
        self.pages.addWidget(self.queue)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        # 右下角浮层：必须是 central 的子控件，才能盖在页面上
        self.toasts = ToastStack(central)

    def _wire(self) -> None:
        self.topbar.navChanged.connect(self._on_nav)
        self.topbar.searchChanged.connect(self.library.set_query)
        self.topbar.themeToggled.connect(self.toggle_theme)
        self.topbar.settingsRequested.connect(self.open_settings)

        self.library.scanRequested.connect(lambda: self.start_scan(announce=True))
        self.library.pickFolderRequested.connect(self.pick_folder)
        self.library.exportRequested.connect(lambda rec: self.export_clips([rec]))
        self.library.exportManyRequested.connect(self.export_clips)
        self.library.namingHelpRequested.connect(self.show_naming_help)

        for key, fn in (("F5", lambda: self.start_scan(announce=True)),
                        ("Ctrl+O", self.pick_folder),
                        ("Ctrl+1", lambda: self.topbar.set_page(PAGE_CLIPS)),
                        ("Ctrl+2", lambda: self.topbar.set_page(PAGE_QUEUE))):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self.toasts.reposition()

    def _on_nav(self, index: int) -> None:
        self.pages.setCurrentIndex(max(0, min(index, self.pages.count() - 1)))

    # ---------------- 扫描 ----------------
    def scan_roots(self) -> list[Path]:
        return default_scan_roots(self.settings.get("scan_roots", []) or [])

    def start_scan(self, announce: bool = False) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        roots = self.scan_roots()
        self._scan_worker = ScanWorker(self.ff, roots, self)
        self._scan_worker.progress.connect(
            lambda p, n: self.library.count.setText(f"扫描中… 已找到 {n}"))
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()
        if announce:
            self.library.count.setText("扫描中…")

    def _on_scan_done(self, recs: list[Recording], unmatched: list | None = None) -> None:
        self._unmatched = list(unmatched or [])
        self.library.set_recordings(recs)
        self.library.set_unmatched(self._unmatched)
        if recs:
            self._empty_shown = False
            return
        # 一条都没扫到：把「差在哪」说清楚，并给几条出路
        if not self._empty_shown:
            self._empty_shown = True
            searched = [str(p) for p in self.scan_roots()]
            dlg = EmptyClipsDialog(self, searched=searched, unmatched=self._unmatched)
            dlg.exec()
            if dlg.action == EmptyClipsDialog.REFRESH:
                QTimer.singleShot(60, lambda: self.start_scan(announce=True))
            elif dlg.action == EmptyClipsDialog.PICK:
                QTimer.singleShot(60, self.pick_folder)
            elif dlg.action == EmptyClipsDialog.NAMING:
                self.show_naming_help()

    def show_naming_help(self) -> None:
        """说明「不是 Steam 来源的 m4s 该怎么改名」——只讲规则，不改识别。"""
        plans = plan_for([u.folder for u in self._unmatched])
        NamingHelpDialog(plans, self).exec()

    def _on_scan_failed(self, msg: str) -> None:
        self.library.count.setText("扫描失败")
        QMessageBox.warning(self, "扫描失败", msg)

    def pick_folder(self) -> None:
        """手动指定剪辑所在位置：选中后记住，下次启动一起扫。"""
        start = ""
        roots = self.settings.get("scan_roots", [])
        if roots:
            start = roots[-1]
        elif steam_clip_dirs():
            start = str(steam_clip_dirs()[0])
        d = QFileDialog.getExistingDirectory(self, "选择剪辑所在文件夹（clip_… 的上一层）", start)
        if not d:
            return
        roots = [str(x) for x in self.settings.get("scan_roots", []) if x != d]
        roots.append(d)
        self.settings.set("scan_roots", roots)
        self.settings.save()
        self.start_scan(announce=True)

    # ---------------- 导出 ----------------
    def output_dir(self) -> Path:
        raw = str(self.settings.get("output_dir") or "").strip()
        if raw:
            p = Path(raw)
            if p.is_dir():
                return p
        return default_output_dir()

    def export_clips(self, recs: list[Recording]) -> None:
        """多选时**逐个导出多个文件**，不是合并成一个。"""
        if not recs:
            return
        if not self.ff.available:
            QMessageBox.warning(self, "无法导出", "没有找到 FFmpeg，请先在设置里指定。")
            return
        out_dir = self.output_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法导出", f"输出目录不可写：{exc}")
            return

        compress = bool(self.settings.get("compress", False))
        for rec in recs:
            out = build_output_path(out_dir, rec.title)
            job = ExportJob(src="", out=out, title=rec.title, duration=rec.duration,
                            compress=compress, rec=rec,
                            segments=len(rec.source_files()),
                            src_size=rec.size, missing=0)
            self.queue.add_job(job)
            self.toasts.begin(rec.key, rec.title)
            self.toasts.progress(rec.key, 0.0, "准备中…")
        self.topbar.set_page(PAGE_QUEUE)
        self._ensure_queue_running()

    def _ensure_queue_running(self) -> None:
        if self._runner is not None and self._runner.isRunning():
            return
        pending = self.queue.pending_jobs()
        if not pending:
            return
        self._runner_idx = {i: self.queue.jobs.index(job) for i, job in enumerate(pending)}
        self._runner = ExportRunner(pending, self.preparer, self.exporter, self)
        self._runner.jobStarted.connect(self._on_job_started)
        self._runner.jobProgress.connect(self._on_job_progress)
        self._runner.jobFinished.connect(self._on_job_finished)
        self._runner.finishedAll.connect(self._on_queue_finished)
        self._runner.start()

    def _on_job_started(self, idx: int) -> None:
        real = self._runner_idx.get(idx)
        if real is None:
            return
        job = self.queue.jobs[real]
        self.queue.update_row(real)
        if job.rec is not None:
            self.toasts.progress(job.rec.key, 0.0, "拼接分片…")

    def _on_job_progress(self, idx: int, p: float, msg: str) -> None:
        real = self._runner_idx.get(idx)
        if real is None:
            return
        job = self.queue.jobs[real]
        self.queue.update_row(real)
        if job.rec is not None:
            self.toasts.progress(job.rec.key, p, msg or "合并中")

    def _on_job_finished(self, idx: int) -> None:
        real = self._runner_idx.get(idx)
        if real is None:
            return
        job = self.queue.jobs[real]
        self.queue.update_row(real)
        key = job.rec.key if job.rec is not None else job.title
        if job.status == "done":
            self.toasts.finish(key, True, f"已导出 · {job.out.name}")
        elif job.status == "canceled":
            self.toasts.finish(key, False, "已取消")
        else:
            self.toasts.finish(key, False, job.message or "导出失败")
        # 这条的临时文件用完就删，别攒到退出
        if job.src:
            self.preparer.unpin(job.src)
            self.preparer.release_path(job.src)

    def _on_queue_finished(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None and runner.isRunning():
            runner.wait(2000)
        self.queue.refresh_all()
        # 收尾兜底：jobFinished 与 finishedAll 是连续发出的，最后一条的
        # 单条回调有可能还没被处理就被这里清掉映射，所以统一再扫一遍。
        for job in self.queue.jobs:
            if job.status in ("done", "failed", "canceled") and job.src:
                self.preparer.unpin(job.src)
                self.preparer.release_path(job.src)
        self._runner_idx.clear()
        QTimer.singleShot(30, self._ensure_queue_running)

    # ---------------- 其它 ----------------
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == SettingsDialog.Accepted:
            dlg.apply()
            self.ff = FFmpeg(self.settings.get("ffmpeg_dir", ""))
            self.preparer.reconfigure(self.ff, self.settings.get("temp_dir", ""))
            self.exporter = Exporter(self.ff, self.settings.get("temp_dir", ""))
            self.scanner = Scanner(self.ff)
            self._update_ffmpeg_banner()

    def _update_ffmpeg_banner(self) -> None:
        self.banner.setVisible(not self.ff.available)

    def toggle_theme(self) -> None:
        dark = theme.current().mode == "light"
        tokens = theme.DARK if dark else theme.LIGHT
        theme.apply(QApplication.instance(), tokens)
        self.settings.set("theme", "dark" if dark else "light")
        self.settings.save()
        self.topbar.set_theme_icon(tokens.mode)
        self._restyle_tree(self.centralWidget())
        self.library.refresh_active()
        self.toasts.restyle()
        self._style_banner()
        self.update()

    def _style_banner(self) -> None:
        c = theme.current()
        self.banner.setStyleSheet(
            f"background:{c.surface_2}; color:{c.warn}; border:none;"
            f"padding:8px 14px; text-align:left; font-size:12.5px; border-radius:0;")

    def _restyle_tree(self, widget: QWidget) -> None:
        for w in [widget, *widget.findChildren(QWidget)]:
            st = w.style()
            st.unpolish(w)
            st.polish(w)
            QWidget.update(w)   # 部分子类重载了 update，需显式调基类

    # ---------------- 拖拽 ----------------
    def dragEnterEvent(self, ev) -> None:  # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:  # noqa: N802
        for url in ev.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                roots = [str(x) for x in self.settings.get("scan_roots", []) if x != str(p)]
                roots.append(str(p))
                self.settings.set("scan_roots", roots)
                self.settings.save()
                self.start_scan(announce=True)
                break

    # ---------------- 退出 ----------------
    def closeEvent(self, ev) -> None:  # noqa: N802
        # 1) 先取消导出，否则关窗后 ffmpeg 变孤儿进程继续写盘
        runner = self._runner
        if runner is not None:
            runner.stop()
            if runner.isRunning():
                runner.wait(3000)
        # 2) 扫描线程：先发停止信号，超时才强杀
        w = self._scan_worker
        if w is not None and w.isRunning():
            w.stop()
            if not w.wait(2500):
                w.terminate()
                w.wait(1500)
        # 3) 清空会话临时文件：正常退出后磁盘上不留任何中间产物
        self.preparer._pinned.clear()
        try:
            self.preparer.cleanup_all()
        except OSError:
            pass
        super().closeEvent(ev)
