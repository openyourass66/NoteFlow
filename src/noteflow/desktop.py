"""NoteFlow desktop window and its single background job."""

import logging
import math
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from threading import Event
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QThread, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .analysis import analyze_media
from .desktop_settings import Tools, edit_tools, load_tools
from .errors import NoteFlowError
from .export import PROGRAMS, export_score
from .media import MEDIA_SUFFIXES, probe
from .process import Cancelled, check_cancelled
from .score import BPM_MAX, BPM_MIN, KEYS, ScoreSettings, build_score, rekey
from .score_view import ScoreView
from .synthesis import render_preview

LOG = logging.getLogger("noteflow")


class Job(QObject):
    progress = Signal(str)
    finished = Signal()

    def __init__(self, operation, cancel):
        super().__init__()
        self.operation, self.cancel = operation, cancel
        self.outcome = None

    @Slot()
    def run(self):
        start = perf_counter()
        try:
            result = self.operation(self.cancel, self.progress.emit)
            check_cancelled(self.cancel)
            outcome = (result, None)
        except (Cancelled, NoteFlowError) as error:
            outcome = (None, error)
        except Exception as error:
            LOG.error("Unexpected worker error: %s", type(error).__name__)
            outcome = (None, NoteFlowError("UNEXPECTED", "worker", "任务失败，请重试。"))
        LOG.info("Worker finished in %.2f s", perf_counter() - start)
        self.outcome = outcome
        self.finished.emit()


def cache_directory() -> Path:
    default = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    location = Path(os.environ.get("NOTEFLOW_CACHE_DIR") or default or Path(gettempdir()) / "NoteFlow")
    location.mkdir(parents=True, exist_ok=True)
    return location.resolve()


class MainWindow(QMainWindow):
    def __init__(self, cache: Path, *, settings: QSettings | None = None, tools: Tools | None = None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings()
        self.tools = tools or load_tools(self.settings)
        self.workspace = TemporaryDirectory(prefix="session-", dir=cache, ignore_cleanup_errors=True)
        self.workdir = Path(self.workspace.name)
        self.media = self.analysis = self.score = None
        self._revision = 0
        self._thread = self._worker = self._cancel = self._callback = None
        self._pending_source = None
        self._closing = False
        self._preview_path = self._player = None
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.65)
        self.setWindowTitle("NoteFlow · 旋律简谱")
        self.setAcceptDrops(True)
        self.resize(1000, 680)
        self.setMinimumSize(680, 470)
        self._build_interface()
        self._sync_controls()

    def _build_interface(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        title = QLabel("NoteFlow")
        font = QFont(title.font())
        font.setPointSize(25)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(QLabel("将本地单声部旋律转换为数字简谱"))

        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)
        self.open_button = self._button(toolbar, "打开文件…", self.choose_source)
        self.generate_button = self._button(toolbar, "生成简谱", self.generate)
        self.cancel_button = self._button(toolbar, "取消任务", self.cancel_job)
        toolbar.addStretch()
        self.settings_button = self._button(toolbar, "工具设置…", self.configure_tools)

        self.source_label = QLabel("尚未导入媒体")
        self.source_label.setWordWrap(True)
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source_label)

        controls = QHBoxLayout()
        layout.addLayout(controls)
        self.bpm = QDoubleSpinBox()
        self.bpm.setRange(BPM_MIN, BPM_MAX)
        self.bpm.setDecimals(1)
        self.bpm.setValue(120)
        self.offset = QDoubleSpinBox()
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.01)
        self.key = QComboBox()
        self.key.addItems(KEYS)
        self._field(controls, "速度 (BPM)", self.bpm)
        self._field(controls, "首拍偏移 (秒)", self.offset)
        self._field(controls, "主音", self.key)
        self.apply_button = self._button(controls, "应用校准", self.apply_calibration)
        controls.addStretch()
        self.bpm.valueChanged.connect(self._update_offset_limit)
        self._update_offset_limit()

        self.score_view = ScoreView()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.score_view)
        layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.instrument = QComboBox()
        self.instrument.addItems(PROGRAMS)
        self._field(actions, "音色", self.instrument)
        self.play_button = self._button(actions, "播放", self.play)
        self.stop_button = self._button(actions, "停止", self.stop_playback)
        self.instrument.currentIndexChanged.connect(self._change_instrument)
        actions.addStretch()
        self.txt_button = self._button(actions, "导出 TXT…", lambda: self.export(False))
        self.midi_button = self._button(actions, "导出 MIDI…", lambda: self.export(True))

        feedback = QHBoxLayout()
        layout.addLayout(feedback)
        self.status = QLabel("可打开文件或把文件拖到窗口。")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setMinimumHeight(30)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(105)
        self.progress.setAccessibleName("后台任务进度")
        feedback.addWidget(self.status, 1)
        feedback.addWidget(self.progress)
        QShortcut(QKeySequence.StandardKey.Open, self, self.open_button.click)
        QShortcut(QKeySequence("Ctrl+G"), self, self.generate_button.click)
        QShortcut(QKeySequence("Escape"), self, self.cancel_button.click)

    @staticmethod
    def _button(layout, text, action):
        button = QPushButton(text)
        button.setMinimumHeight(44)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    @staticmethod
    def _field(layout, text, widget):
        label = QLabel(text)
        label.setBuddy(widget)
        widget.setMinimumHeight(44)
        widget.setAccessibleName(text)
        layout.addWidget(label)
        layout.addWidget(widget)

    def _update_offset_limit(self):
        limit_ms = math.ceil(ScoreSettings(self.bpm.value()).tempo_us / 1000) - 1
        self.offset.setMaximum(limit_ms / 1000)

    def _sync_controls(self):
        busy, ready = self._thread is not None, self.score is not None
        self.open_button.setEnabled(not self._closing)
        self.settings_button.setEnabled(not busy)
        self.generate_button.setEnabled(not busy and self.media is not None)
        self.cancel_button.setEnabled(busy and not self._cancel.is_set())
        for control in (self.bpm, self.offset, self.key, self.apply_button,
                        self.instrument, self.play_button, self.txt_button, self.midi_button):
            control.setEnabled(ready and not busy)
        self.stop_button.setEnabled(self._player is not None)
        self.progress.setVisible(busy)

    def _status(self, text):
        self.status.setText(text)

    @Slot(str)
    def _job_progress(self, text):
        if self._cancel and not self._cancel.is_set():
            self._status(text)

    def _start(self, label, operation, callback):
        if self._thread is not None:
            return
        self._cancel = Event()
        self._callback = callback
        self._thread = QThread(self)
        self._worker = Job(operation, self._cancel)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._job_progress)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._finish_job)
        LOG.info("%s", label)
        self._status(label)
        self._sync_controls()
        self._thread.start()

    @Slot()
    def _finish_job(self):
        # QThread emits finished before its native thread-local cleanup is complete.
        self._thread.wait()
        cancelled = self._cancel.is_set()
        callback = self._callback
        value, error = self._worker.outcome or (None, NoteFlowError("UNEXPECTED", "worker", "后台任务中断。"))
        self._thread.deleteLater()
        self._thread = self._worker = self._cancel = self._callback = None
        if self._closing:
            self.close()
            return
        if self._pending_source is not None:
            path, self._pending_source = self._pending_source, None
            self.open_source(path)
            return
        if cancelled or isinstance(error, Cancelled):
            self._remove_preview()
            self._status("任务已取消，可以重试。")
        elif error:
            self._remove_preview()
            LOG.warning("%s %s", error.stage, error.code)
            self._status(str(error))
        else:
            callback(value)
        self._sync_controls()

    def cancel_job(self):
        if self._cancel is not None:
            self._cancel.set()
            self._status("正在取消，等待当前阶段结束…")
            self._sync_controls()

    def configure_tools(self):
        self.tools = edit_tools(self, self.settings, self.tools)

    def choose_source(self):
        patterns = " ".join(f"*{suffix}" for suffix in MEDIA_SUFFIXES)
        selected, _ = QFileDialog.getOpenFileName(self, "选择本地媒体", "", f"媒体文件 ({patterns})")
        if selected:
            self.open_source(Path(selected))

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and not self._closing:
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and not self._closing:
            event.acceptProposedAction()
            self.open_source(Path(urls[0].toLocalFile()))

    def open_source(self, source: Path):
        if self._thread is not None:
            self._pending_source = source
            self.cancel_job()
            return
        self._stop_player()
        self.media = self.analysis = self.score = None
        self.score_view.set_score(None)
        self.source_label.setText(source.name)
        ffprobe = self.tools.ffprobe
        self._start("正在检查音轨…", lambda cancel, _: probe(source, ffprobe, cancel=cancel), self._imported)

    def _imported(self, media):
        self.media = media
        self._show_media(media.duration_s)
        self._status("音轨已就绪，点击生成简谱。")

    def _show_media(self, duration):
        length = f"{duration:.2f} 秒" if duration is not None else "时长待解码确认"
        self.source_label.setText(f"{self.media.path.name}   ·   {length}   ·   音轨 {self.media.stream_index} / {self.media.codec}")

    def generate(self):
        if self.media is None or self._thread is not None:
            return
        self._stop_player()
        media, ffmpeg, workdir = self.media, self.tools.ffmpeg, self.workdir
        self._revision += 1
        revision = self._revision

        def generate(cancel, progress):
            analysis = analyze_media(media, ffmpeg=ffmpeg, find_beats=True, workdir=workdir,
                                     cancel=cancel, progress=progress)
            progress("正在生成简谱…")
            beat = analysis.beat
            score = build_score(analysis.notes, ScoreSettings(beat.bpm, beat.first_beat_s), revision)
            return analysis, score

        self._start("正在生成简谱…", generate, self._generated)

    def _generated(self, result):
        self.analysis, score = result
        self._show_media(self.analysis.duration_s)
        self._publish_score(score, calibrated=self.analysis.beat.reliable)

    def _publish_score(self, score, *, calibrated=True):
        self.score = score
        self.score_view.set_score(score)
        self.bpm.setValue(score.settings.bpm)
        self.offset.setValue(score.settings.first_beat_s)
        self.key.setCurrentIndex(score.settings.tonic_pc)
        message = f"{len(score.measures)} 小节，{len(score.grid.notes)} 个音符。"
        if not calibrated:
            message += "拍点证据不足，当前使用 120 BPM，请手动校准。"
        if score.grid.overlap_drops / len(self.analysis.notes) > 0.3:
            message += "重叠音较多，可能含伴奏或和弦。"
        self._status(message)

    def apply_calibration(self):
        if self.score is None or self._thread is not None:
            return
        self._stop_player()
        previous, notes = self.score, self.analysis.notes
        settings = ScoreSettings(self.bpm.value(), self.offset.value(), self.key.currentIndex())
        self._revision += 1
        revision = self._revision

        def rebuild(_cancel, _progress):
            if (settings.bpm, settings.first_beat_s) == (previous.settings.bpm, previous.settings.first_beat_s):
                return rekey(previous, settings.tonic_pc, revision)
            return build_score(notes, settings, revision)

        self._start("正在应用校准…", rebuild, self._publish_score)

    def play(self):
        if self.score is None or self._thread is not None:
            return
        self._stop_player()
        if not self.tools.soundfont:
            self._status("请在工具设置中选择包含所需乐器的 SF2 音源。")
            self._sync_controls()
            return
        score, program = self.score, PROGRAMS[self.instrument.currentText()]
        synth, soundfont = self.tools.fluidsynth, Path(self.tools.soundfont).resolve()
        target = self.workdir / f"preview-{uuid4().hex}.wav"
        self._preview_path = target
        self._start("正在渲染试听…", lambda cancel, _: render_preview(score, program, soundfont, target, synth, cancel),
                    self._play_rendered)

    def _play_rendered(self, path):
        player = QMediaPlayer(self)
        self._player = player
        player.setAudioOutput(self._audio)
        player.errorOccurred.connect(lambda _code, _detail: self._playback_done(player, failed=True))
        player.mediaStatusChanged.connect(lambda state: self._playback_done(player) if state == QMediaPlayer.MediaStatus.EndOfMedia else None)
        self._status("正在播放试听…")
        player.setSource(QUrl.fromLocalFile(str(path)))
        if self._player is player:
            player.play()

    def _playback_done(self, player, *, failed=False):
        if self._player is not player:
            return
        self._stop_player()
        self._status("播放失败，请检查系统音频输出后重试。" if failed else "播放结束。")
        self._sync_controls()

    def stop_playback(self):
        self._stop_player()
        self._status("已停止播放。")
        self._sync_controls()

    def _change_instrument(self):
        if self._player is not None:
            self.play()

    def _stop_player(self):
        player, self._player = self._player, None
        if player is not None:
            player.stop()
            player.setSource(QUrl())
            player.setAudioOutput(None)
            player.deleteLater()
        self._remove_preview()

    def _remove_preview(self):
        path, self._preview_path = self._preview_path, None
        if path is not None:
            self._delete_preview(path)

    @staticmethod
    def _delete_preview(path, attempts=2):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if attempts:
                QTimer.singleShot(150, lambda: MainWindow._delete_preview(path, attempts - 1))

    def export(self, midi):
        if self.score is None or self._thread is not None:
            return
        suffix = ".mid" if midi else ".txt"
        destination, _ = QFileDialog.getSaveFileName(
            self, "导出 MIDI" if midi else "导出简谱文本", self.media.path.stem + suffix,
            "MIDI (*.mid *.midi)" if midi else "文本 (*.txt)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not destination:
            return
        path = Path(destination)
        extensions = {".mid", ".midi"} if midi else {".txt"}
        if path.suffix.lower() not in extensions:
            path = Path(str(path) + suffix)
        overwrite = path.exists()
        if overwrite and QMessageBox.question(self, "覆盖文件", f"覆盖 {path.name}？") != QMessageBox.StandardButton.Yes:
            return
        try:
            export_score(self.score, PROGRAMS[self.instrument.currentText()], path, midi=midi, overwrite=overwrite)
        except OSError:
            self._status("导出失败，请检查写入权限或选择新的文件名。")
        else:
            self._status(f"已导出 {path.name}。")

    def closeEvent(self, event):
        if self._thread is not None:
            event.ignore()
            self._closing = True
            self._pending_source = None
            self.cancel_job()
            return
        self._stop_player()
        self.workspace.cleanup()
        event.accept()


def main(source: Path | None = None) -> int:
    app = QApplication(["NoteFlow"])
    app.setApplicationName("NoteFlow")
    app.setOrganizationName("NoteFlow")
    try:
        cache = cache_directory()
        os.environ.setdefault("NUMBA_CACHE_DIR", str(cache / "numba"))
        handler = RotatingFileHandler(cache / "noteflow.log", maxBytes=262144, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)
        window = MainWindow(cache)
    except OSError:
        QMessageBox.critical(None, "NoteFlow", "无法创建本地缓存，请检查应用数据目录的写入权限。")
        return 1
    window.show()
    if source is not None:
        window.open_source(source)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) == 2 else None))
