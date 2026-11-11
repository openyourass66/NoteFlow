"""NoteFlow desktop window and its single background job."""

import logging
import math
import os
import shutil
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from threading import Event
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QThread, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QLabel, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QTableWidgetItem,
)

from .analysis import analyze_media
from .desktop_settings import Tools, edit_tools, load_tools
from .desktop_ui import build_interface
from .errors import NoteFlowError
from .export import PROGRAMS, export_score
from .media import MEDIA_SUFFIXES, decode_original, probe
from .process import Cancelled, check_cancelled
from .project import Project, load_project, save_project
from .notes import NoteEvent
from .score import ScoreSettings, build_score, rekey
from .separation import separate
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
        self.stems = self._stem_workspace = None
        self._project_workspace = self._loading_workspace = None
        self.project_path = None
        self.source_name = ""
        self._dirty = False
        self._edited_notes = None
        self._undo, self._redo = [], []
        self._analysis_vocals = False
        self._revision = 0
        self._thread = self._worker = self._cancel = self._callback = None
        self._pending_source = None
        self._closing = False
        self._preview_path = self._player = self._playing = None
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.65)
        self.setWindowTitle("NoteFlow · 旋律简谱")
        self.setAcceptDrops(True)
        self.resize(1220, 820)
        self.setMinimumSize(1000, 680)
        self._build_interface()
        self.score_view.note_clicked.connect(self._score_clicked)
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.volume.setValue(self.settings.value("playback/volume", 65, int))
        self._load_recent()
        self._sync_controls()

    def _build_interface(self):
        build_interface(self)

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
        self.open_project_button.setEnabled(not self._closing)
        self.save_button.setEnabled(not busy and self.media is not None)
        self.source_mode.setEnabled(not busy and self.media is not None)
        self.source_mode.model().item(1).setEnabled(self.stems is not None)
        self.recent.setEnabled(not self._closing)
        self.note_table.setEnabled(ready and not busy)
        for control in (self.add_note_button, self.delete_note_button, self.lower_button,
                        self.higher_button, self.down_octave_button, self.up_octave_button):
            control.setEnabled(ready and not busy)
        self.undo_button.setEnabled(bool(self._undo) and not busy)
        self.redo_button.setEnabled(bool(self._redo) and not busy)
        self.audio_export_button.setEnabled(not busy and (ready or self.stems is not None))
        self.original_button.setEnabled(not busy and self.media is not None)
        self.separate_button.setEnabled(not busy and self.media is not None and self.stems is None)
        for control in (self.vocals_button, self.accompaniment_button):
            control.setEnabled(not busy and self.stems is not None)
        self.cancel_button.setEnabled(busy and not self._cancel.is_set())
        self.cancel_button.setVisible(busy)
        for control in (self.bpm, self.offset, self.key, self.apply_button,
                        self.instrument, self.melody_button, self.play_button, self.txt_button, self.midi_button):
            control.setEnabled(ready and not busy)
        self.stop_button.setEnabled(self._player is not None)
        self.pause_button.setEnabled(self._player is not None)
        self.timeline.setEnabled(self._player is not None)
        if ready and not self.score.melody:
            self.melody_button.setEnabled(False)
            self.play_button.setEnabled(False)
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
        if (cancelled or error or self._pending_source is not None or self._closing) and self._loading_workspace:
            self._loading_workspace.cleanup()
            self._loading_workspace = None
        if self.stems is None and (cancelled or error):
            self._clear_stems()
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
        source = Path(source)
        if self._thread is not None:
            self._pending_source = source
            self.cancel_job()
            return
        if not self._confirm_discard(lambda: self.open_source(source)):
            return
        if source.suffix.lower() == ".noteflow":
            self._open_project(source)
            return
        self._stop_player()
        ffprobe = self.tools.ffprobe
        self._start("正在检查音轨…", lambda cancel, _: probe(source, ffprobe, cancel=cancel), self._imported)

    def _imported(self, media):
        self._clear_session()
        self.media = media
        self.source_name = media.path.name
        self._update_title()
        self._show_media(media.duration_s)
        self._status("音轨已就绪。歌曲混音可先分离人声与伴奏，清唱或独奏可直接生成简谱。")

    def _show_media(self, duration):
        length = f"{duration:.2f} 秒" if duration is not None else "时长待解码确认"
        self.source_label.setText(f"{self.source_name}   ·   {length}")

    def generate(self):
        if self.media is None or self._thread is not None:
            return
        self._stop_player()
        media, ffmpeg, workdir = self.media, self.tools.ffmpeg, self.workdir
        vocals = self.stems.vocals if self.stems and self.source_mode.currentIndex() == 1 else None
        self._generating_vocals = vocals is not None
        if self._edited_notes is not None and QMessageBox.question(
            self, "重新识别", "重新识别将替换手动修正的音符，继续？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._revision += 1
        revision = self._revision

        def generate(cancel, progress):
            analysis = analyze_media(media, ffmpeg=ffmpeg, find_beats=True, workdir=workdir,
                                     cancel=cancel, progress=progress, vocals=vocals, verify_pitch=True)
            progress("正在生成简谱…")
            beat = analysis.beat
            score = build_score(analysis.notes, ScoreSettings(beat.bpm, beat.first_beat_s), revision)
            return analysis, score

        self._start("正在生成简谱…", generate, self._generated)

    def _generated(self, result):
        self.analysis, score = result
        self._edited_notes = None
        self._undo.clear()
        self._redo.clear()
        self._analysis_vocals = self._generating_vocals
        self._show_media(self.analysis.duration_s)
        self._publish_score(score, calibrated=self.analysis.beat.reliable)
        self._mark_dirty()

    def _publish_score(self, score, *, calibrated=True):
        self.score = score
        self.score_view.set_score(score)
        self._refresh_editor()
        self.bpm.setValue(score.settings.bpm)
        self.offset.setValue(score.settings.first_beat_s)
        self.key.setCurrentIndex(score.settings.tonic_pc)
        source = "人声" if self._analysis_vocals else "原曲"
        message = f"{source}简谱，{len(score.measures)} 小节，{len(score.grid.notes)} 个音符。"
        if not calibrated:
            message += "拍点证据不足，当前使用 120 BPM，请手动校准。"
        if self.analysis.notes and score.grid.overlap_drops / len(self.analysis.notes) > 0.3:
            message += "重叠音较多，可能含伴奏或和弦。"
        self._status(message)

    def apply_calibration(self):
        if self.score is None or self._thread is not None:
            return
        self._stop_player()
        previous = self.score
        notes = self.analysis.notes if self._edited_notes is None else self._edited_notes
        settings = ScoreSettings(self.bpm.value(), self.offset.value(), self.key.currentIndex())
        self._revision += 1
        revision = self._revision

        def rebuild(_cancel, _progress):
            if (settings.bpm, settings.first_beat_s) == (previous.settings.bpm, previous.settings.first_beat_s):
                return rekey(previous, settings.tonic_pc, revision)
            return build_score(notes, settings, revision)

        self._start("正在应用校准…", rebuild, self._calibrated)

    def play_original(self):
        if self.media is None or self._thread is not None:
            return
        self._stop_player()
        media, ffmpeg = self.media, self.tools.ffmpeg
        target = self.workdir / f"original-{uuid4().hex}.wav"
        self._preview_path = target
        self._start("正在准备原曲音轨…", lambda cancel, _: decode_original(media, target, ffmpeg, cancel),
                    lambda path: self._play_rendered(path, "原曲"))

    def separate_tracks(self):
        if self.media is None or self.stems is not None or self._thread is not None:
            return
        if not self.tools.demucs_python:
            self._status("请先在工具设置中选择已安装 Demucs 的 Python。")
            return
        try:
            self._stem_workspace = TemporaryDirectory(prefix="tracks-", dir=self.workdir, ignore_cleanup_errors=True)
        except OSError:
            self._status("无法创建分轨工作目录，请检查缓存目录和磁盘空间。")
            return
        self._stop_player()
        destination = Path(self._stem_workspace.name) / "stems"
        media, tools = self.media, self.tools
        self._start("正在分离人声与伴奏，首次运行会下载模型…",
                    lambda cancel, _: separate(media, destination, python=tools.demucs_python,
                                               ffmpeg=tools.ffmpeg, cancel=cancel),
                    self._tracks_ready)

    def _tracks_ready(self, stems):
        self.stems = stems
        self.source_mode.setCurrentIndex(1)
        self._mark_dirty()
        self._status("人声与伴奏已分离，可以分别播放。生成简谱将识别人声。")

    def _clear_stems(self):
        self.stems = None
        if self._stem_workspace is not None:
            self._stem_workspace.cleanup()
            self._stem_workspace = None

    def play_stem(self, *, vocals):
        if self.stems is None or self._thread is not None:
            return
        self._stop_player()
        path, label = (self.stems.vocals, "人声") if vocals else (self.stems.accompaniment, "伴奏")
        self._play_rendered(path, label)
        self._sync_controls()

    def play(self, *, original_timing=False):
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
        label = "旋律" if original_timing else "简谱"
        self._start(f"正在渲染{label}…", lambda cancel, _: render_preview(
            score, program, soundfont, target, synth, cancel, original_timing=original_timing),
            lambda path: self._play_rendered(path, label))

    def _play_rendered(self, path, label):
        player = QMediaPlayer(self)
        self._player = player
        self._playing = label
        player.setAudioOutput(self._audio)
        player.setPlaybackRate((0.5, 0.75, 1, 1.25, 1.5)[self.rate.currentIndex()])
        player.durationChanged.connect(lambda duration: self.timeline.setRange(0, duration) if self._player is player else None)
        player.positionChanged.connect(lambda position: self._position_changed(position) if self._player is player else None)
        player.playbackStateChanged.connect(lambda state: self.pause_button.setText(
            "继续" if state == QMediaPlayer.PlaybackState.PausedState else "暂停") if self._player is player else None)
        player.errorOccurred.connect(lambda _code, _detail: self._playback_done(player, failed=True))
        player.mediaStatusChanged.connect(lambda state: self._playback_done(player) if state == QMediaPlayer.MediaStatus.EndOfMedia else None)
        self._status(f"正在播放{label}…")
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
        if self.media is not None:
            self._mark_dirty()
        if self._playing in ("旋律", "简谱"):
            self.play(original_timing=self._playing == "旋律")

    def _stop_player(self):
        player, self._player = self._player, None
        self._playing = None
        self.timeline.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.pause_button.setText("暂停")
        self.score_view.set_active_note(None)
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

    def _update_title(self):
        title = self.project_path.stem if self.project_path else (Path(self.source_name).stem or "新的音乐项目")
        self.project_label.setText(title + (" · 未保存" if self._dirty else ""))
        self.setWindowTitle(f"{title}{' *' if self._dirty else ''} — NoteFlow")

    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    def _confirm_discard(self, continuation=None):
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self, "保存项目", "当前项目有未保存的内容。是否保存后继续？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            self.save_project(after=continuation)
        return answer == QMessageBox.StandardButton.Discard

    def _clear_session(self):
        self._stop_player()
        self._clear_stems()
        if self._project_workspace:
            self._project_workspace.cleanup()
            self._project_workspace = None
        self.media = self.analysis = self.score = self.project_path = None
        self._edited_notes = None
        self._undo.clear()
        self._redo.clear()
        self._dirty = self._analysis_vocals = False
        self.source_mode.setCurrentIndex(0)
        self.score_view.set_score(None)
        self._refresh_editor()

    def _load_recent(self):
        paths = self.settings.value("projects/recent", [], list)
        self.recent.clear()
        for path in paths[:8]:
            item = QListWidgetItem(Path(path).stem)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.recent.addItem(item)

    def _remember_project(self, path):
        paths = self.settings.value("projects/recent", [], list)
        path = str(path.resolve())
        self.settings.setValue("projects/recent", [path] + [p for p in paths if p != path][:7])
        self._load_recent()

    def choose_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", "NoteFlow 项目 (*.noteflow)")
        if path:
            self.open_source(Path(path))

    def _open_project(self, path):
        try:
            self._loading_workspace = TemporaryDirectory(prefix="project-", dir=self.workdir, ignore_cleanup_errors=True)
        except OSError:
            self._status("无法创建项目工作目录，请检查磁盘空间。")
            return
        directory = Path(self._loading_workspace.name)

        def loaded(project):
            self._clear_session()
            self._project_workspace, self._loading_workspace = self._loading_workspace, None
            self.media, self.analysis, self.stems = project.media, project.analysis, project.stems
            self.source_name = project.name
            self.project_path = path.resolve()
            self._edited_notes = project.edited_notes
            self._analysis_vocals = project.vocal_score
            self.instrument.setCurrentText(project.instrument)
            self.source_mode.setCurrentIndex(1 if project.vocal_score else 0)
            if project.score:
                self._publish_score(project.score)
            self._dirty = False
            self._show_media(self.media.duration_s)
            self._update_title()
            self._remember_project(path)
            self._status("项目已恢复，可以继续编辑和试听。")

        self._start("正在打开项目…", lambda cancel, _: load_project(path, directory, cancel), loaded)

    def save_project(self, _checked=False, *, save_as=False, after=None):
        if self.media is None or self._thread is not None:
            return
        path = self.project_path
        if path is None or save_as:
            chosen, _ = QFileDialog.getSaveFileName(
                self, "保存项目", str(path or Path(self.source_name).with_suffix(".noteflow")),
                "NoteFlow 项目 (*.noteflow)",
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
            if not chosen:
                return
            path = Path(chosen)
            if path.suffix.lower() != ".noteflow":
                path = Path(str(path) + ".noteflow")
            if path.exists() and QMessageBox.question(self, "覆盖项目", f"覆盖 {path.name}？") != QMessageBox.StandardButton.Yes:
                return
        project = Project(self.source_name, self.media, self.analysis, self.score, self.stems,
                          self._edited_notes, self.instrument.currentText(), self._analysis_vocals)

        def saved(_):
            self.project_path = path.resolve()
            self._dirty = False
            self._update_title()
            self._remember_project(path)
            self._status("项目已保存，原曲、分轨和音符已一起写入。")
            if after:
                after()

        self._start("正在保存项目…", lambda cancel, _: save_project(project, path, self.tools.ffmpeg, cancel), saved)

    def _refresh_editor(self):
        self.note_table.blockSignals(True)
        notes = self.score.melody if self.score else ()
        self.note_table.setRowCount(len(notes))
        names = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
        for row, note in enumerate(notes):
            values = (f"{note.start_s:.3f}", f"{note.end_s:.3f}", str(note.midi),
                      f"{names[note.midi % 12]}{note.midi // 12 - 1}", str(note.velocity))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, note.id)
                if column == 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.note_table.setItem(row, column, item)
        self.note_table.blockSignals(False)

    def _record_change(self):
        self._undo.append((self.score, self._edited_notes))
        self._undo = self._undo[-100:]
        self._redo.clear()
        self._stop_player()

    def _calibrated(self, score):
        self._record_change()
        self._publish_score(score)
        self._mark_dirty()

    def _apply_notes(self, notes):
        self._record_change()
        self._revision += 1
        self._edited_notes = tuple(sorted(notes, key=lambda n: n.start_s))
        self._publish_score(build_score(self._edited_notes, self.score.settings, self._revision))
        self._mark_dirty()
        self._sync_controls()

    def edit_note(self, row, column):
        if self.score is None or self._thread is not None or column == 3:
            return
        notes = list(self.score.melody)
        previous = notes[row]
        fields = {0: "start_s", 1: "end_s", 2: "midi", 4: "velocity"}
        try:
            value = float(self.note_table.item(row, column).text()) if column < 2 else int(self.note_table.item(row, column).text())
            note = replace(previous, **{fields[column]: value})
            if (not all(map(math.isfinite, (note.start_s, note.end_s)))
                    or not 0 <= note.start_s < note.end_s <= self.analysis.duration_s
                    or not 0 <= note.midi <= 127 or not 1 <= note.velocity <= 127
                    or any(n.id != note.id and min(n.end_s, note.end_s) - max(n.start_s, note.start_s) > 0.0001 for n in notes)):
                raise ValueError
        except ValueError:
            self._refresh_editor()
            self._status("请输入有效音符。起止时间须在音轨内且互不重叠，MIDI 音高为 0–127，力度为 1–127。")
            return
        notes[row] = note
        self._apply_notes(notes)
        self._select_note(note.id)

    def _select_note(self, note_id):
        if self.score:
            for row, note in enumerate(self.score.melody):
                if note.id == note_id:
                    self.note_table.selectRow(row)
                    break

    def _score_clicked(self, note_id):
        self._select_note(note_id)
        if self._player and self.score:
            self._player.setPosition(round(self._note_times()[note_id][0] * 1000))

    def _note_selected(self):
        row = self._selected_row()
        if self.score and 0 <= row < len(self.score.melody):
            self.score_view.set_active_note(self.score.melody[row].id)

    def _selected_row(self):
        items = self.note_table.selectedItems()
        return items[0].row() if items else -1

    def transpose_note(self, amount):
        row = self._selected_row()
        if self.score is None or self._thread is not None or not 0 <= row < len(self.score.melody):
            return
        note = self.score.melody[row]
        if 0 <= note.midi + amount <= 127:
            notes = list(self.score.melody)
            notes[row] = replace(note, midi=note.midi + amount)
            self._apply_notes(notes)
            self._select_note(note.id)

    def delete_note(self):
        row = self._selected_row()
        if self.score and self._thread is None and 0 <= row < len(self.score.melody):
            notes = list(self.score.melody)
            del notes[row]
            self._apply_notes(notes)

    def add_note(self):
        if self.score is None or self._thread is not None:
            return
        cursor = 0.0
        for note in self.score.melody:
            if note.start_s - cursor >= 0.125:
                break
            cursor = note.end_s
        end = min(cursor + 0.25, self.analysis.duration_s,
                  next((n.start_s for n in self.score.melody if n.start_s > cursor), self.analysis.duration_s))
        if end - cursor < 0.05:
            self._status("音轨中没有可插入的空隙，请先调整相邻音符的时间。")
            return
        note = NoteEvent(uuid4().hex, cursor, end, 60, 1.0, 80)
        self._apply_notes((*self.score.melody, note))
        self._select_note(note.id)

    def undo(self):
        if self._thread is None and self._undo:
            self._redo.append((self.score, self._edited_notes))
            score, self._edited_notes = self._undo.pop()
            self._stop_player()
            self._publish_score(score)
            self._mark_dirty()
            self._sync_controls()

    def redo(self):
        if self._thread is None and self._redo:
            self._undo.append((self.score, self._edited_notes))
            score, self._edited_notes = self._redo.pop()
            self._stop_player()
            self._publish_score(score)
            self._mark_dirty()
            self._sync_controls()

    def _note_times(self):
        if self._playing == "简谱":
            seconds_per_tick = self.score.settings.tempo_us / 480_000_000
            return {n.id: (n.start_tick * seconds_per_tick, (n.start_tick + n.duration_tick) * seconds_per_tick)
                    for n in self.score.grid.notes}
        return {n.id: (n.start_s, n.end_s) for n in self.score.melody}

    def _position_changed(self, position):
        if not self.timeline.isSliderDown():
            self.timeline.setValue(position)
        duration = self._player.duration() if self._player else 0
        self.time_label.setText(f"{position // 60000:02d}:{position // 1000 % 60:02d} / {duration // 60000:02d}:{duration // 1000 % 60:02d}")
        if self.score:
            note_id = next((key for key, (start, end) in self._note_times().items() if start <= position / 1000 < end), None)
            self.score_view.set_active_note(note_id)

    def toggle_pause(self):
        if self._player:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()

    def seek(self):
        if self._player:
            self._player.setPosition(self.timeline.value())

    def change_rate(self):
        if self._player:
            self._player.setPlaybackRate((0.5, 0.75, 1, 1.25, 1.5)[self.rate.currentIndex()])

    def export_audio(self):
        if self._thread is not None:
            return
        choices = []
        if self.stems:
            choices.extend(("人声", "伴奏"))
        if self.score and self.score.melody:
            choices.extend(("旋律", "简谱"))
        if not choices:
            return
        kind, accepted = QInputDialog.getItem(self, "导出音频", "选择音轨", choices, editable=False)
        if not accepted:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self, "导出 WAV", Path(self.source_name).stem + f"-{kind}.wav", "WAV (*.wav)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() != ".wav":
            path = Path(str(path) + ".wav")
        if path.exists() and QMessageBox.question(self, "覆盖文件", f"覆盖 {path.name}？") != QMessageBox.StandardButton.Yes:
            return
        score, stems, tools = self.score, self.stems, self.tools
        program = PROGRAMS[self.instrument.currentText()]

        def write(cancel, _):
            with TemporaryDirectory(prefix="export-", dir=path.parent) as directory:
                target = Path(directory) / "audio.wav"
                if kind in ("人声", "伴奏"):
                    shutil.copyfile(stems.vocals if kind == "人声" else stems.accompaniment, target)
                else:
                    render_preview(score, program, Path(tools.soundfont), target, tools.fluidsynth,
                                   cancel, original_timing=kind == "旋律")
                check_cancelled(cancel)
                os.replace(target, path)

        self._start("正在导出音频…", write, lambda _: self._status(f"已导出 {path.name}。"))

    def show_help(self):
        QMessageBox.information(self, "使用说明",
            "1. 导入音频或视频。歌曲混音可先分离人声与伴奏。\n"
            "2. 选择识别来源，生成简谱，再校准速度、首拍和主音。\n"
            "3. 在音符编辑页修正音高、起止时间和力度，Ctrl+Z 可撤销。\n"
            "4. 播放时可暂停、拖动进度、调整速度。点击谱面音符可定位。\n"
            "5. Ctrl+S 保存项目。项目包含原曲、分轨和音符，可离线恢复。\n\n"
            "当前支持固定 4/4 拍、恒定速度和最长 120 秒片段。")

    def closeEvent(self, event):
        if self._thread is not None:
            event.ignore()
            self._closing = True
            self._pending_source = None
            self.cancel_job()
            return
        if not self._confirm_discard(self.close):
            self._closing = False
            event.ignore()
            self._sync_controls()
            return
        self._stop_player()
        self._clear_stems()
        if self._project_workspace:
            self._project_workspace.cleanup()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("playback/volume", self.volume.value())
        self.workspace.cleanup()
        event.accept()


def main(source: Path | None = None) -> int:
    app = QApplication(["NoteFlow"])
    app.setStyle("Fusion")
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
