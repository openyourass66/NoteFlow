"""Review candidates, aligned playback and optional diagnostic details."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .desktop_theme import ComboBox
from .review import STATUS_TEXT, fingerprint, save_report
from .review_edit import latest_issues, note_changes

KIND_TEXT = {"pitch": "音高", "octave": "八度", "rhythm": "节奏", "fragmentation": "连贯性",
             "wrong_voice": "声部", "missing_notes": "漏音"}


class ReviewReportDialog(QDialog):
    prepare_requested = Signal()
    locate_requested = Signal(object)
    audition_requested = Signal(object, int)
    apply_requested = Signal(object)
    cancel_requested = Signal()
    restart_requested = Signal()

    def __init__(self, parent, result, current_notes):
        super().__init__(parent)
        self.setWindowTitle("复核结果与乐谱修改")
        self.resize(650, 240)
        self.current = current_notes
        self.signature = fingerprint(current_notes)
        self.busy = False
        self.paths = ()
        self.resume_position = 0

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        self.header = QLabel()
        self.header.setTextFormat(Qt.TextFormat.PlainText)
        self.header.setWordWrap(True)
        self.header.setMinimumWidth(600)
        layout.addWidget(self.header)

        self.candidate_panel = QWidget()
        panel = QVBoxLayout(self.candidate_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        selection = QHBoxLayout()
        label = QLabel("修改候选")
        self.candidate_list = ComboBox()
        self.candidate_list.setAccessibleName("局部修改候选")
        self.candidate_list.setMinimumHeight(36)
        label.setBuddy(self.candidate_list)
        selection.addWidget(label)
        selection.addWidget(self.candidate_list, 1)
        panel.addLayout(selection)

        self.output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.player.mediaStatusChanged.connect(self._loaded)
        self.player.errorOccurred.connect(self._playback_error)
        self.player.playbackStateChanged.connect(self._playback_state)
        track_group = QFrame()
        track_group.setObjectName("tracks")
        tracks = QHBoxLayout(track_group)
        tracks.setContentsMargins(3, 3, 3, 3)
        tracks.setSpacing(2)
        self.track_buttons = []
        for index, name in enumerate(("原曲", "修改前", "候选")):
            button = QPushButton(name)
            button.setObjectName("track")
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _, i=index: self._choose_track(i))
            self.track_buttons.append(button)
            tracks.addWidget(button, 1)
        controls = QHBoxLayout()
        controls.addWidget(track_group, 1)
        self.stop = QPushButton("停止")
        self.stop.setMinimumHeight(36)
        self.stop.clicked.connect(self.player.stop)
        controls.addWidget(self.stop)
        panel.addLayout(controls)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setAccessibleName("对照试听进度")
        self.timeline.sliderReleased.connect(lambda: self.player.setPosition(self.timeline.value()))
        self.player.positionChanged.connect(self._position_changed)
        panel.addWidget(self.timeline)
        layout.addWidget(self.candidate_panel)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setAccessibleName("复核操作状态")
        layout.addWidget(self.status)

        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        self.issue_list = QListWidget()
        self.issue_list.setAccessibleName("复核疑点列表")
        self.issue_list.setMaximumHeight(108)
        details.addWidget(self.issue_list)
        self.issue_detail = QPlainTextEdit()
        self.issue_detail.setReadOnly(True)
        self.issue_detail.setAccessibleName("复核疑点与音符改动")
        self.issue_detail.setFixedHeight(128)
        details.addWidget(self.issue_detail)
        detail_actions = QHBoxLayout()
        self.locate = QPushButton("定位音符")
        self.locate.clicked.connect(self._locate)
        self.export_button = QPushButton("导出记录…")
        self.export_button.clicked.connect(self.export)
        detail_actions.addWidget(self.locate)
        detail_actions.addWidget(self.export_button)
        detail_actions.addStretch()
        details.addLayout(detail_actions)
        self.details.hide()
        layout.addWidget(self.details)

        actions = QHBoxLayout()
        self.details_toggle = QPushButton("查看详情")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setObjectName("quiet")
        self.details_toggle.toggled.connect(self._toggle_details)
        actions.addWidget(self.details_toggle)
        self.restart = QPushButton("重新复核…")
        self.restart.setObjectName("quiet")
        self.restart.clicked.connect(self.restart_requested)
        actions.addWidget(self.restart)
        actions.addStretch()
        self.prepare = QPushButton("生成候选")
        self.apply = QPushButton("应用到简谱")
        for button in (self.prepare, self.apply):
            button.setObjectName("primary")
            button.setMinimumHeight(36)
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.prepare.clicked.connect(self.prepare_requested)
        self.apply.clicked.connect(self._apply)
        self.close_button = QPushButton("关闭")
        self.close_button.setMinimumHeight(36)
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        self.issue_list.currentRowChanged.connect(self._refresh_details)
        self.candidate_list.currentIndexChanged.connect(self._candidate_changed)
        self.set_result(result)
        self.close_button.setFocus()

    def set_result(self, result):
        self.result = result
        self.issues = latest_issues(result)
        self.candidates = tuple(c for c in result.candidates if c.baseline_fingerprint == self.signature)
        stale = self.signature != fingerprint(result.notes)
        summary = "乐谱已修改，可重新生成候选。" if stale else STATUS_TEXT[result.status]
        self.header.setText(summary + f"\n{result.start_s:.2f}–{result.end_s:.2f} 秒 · 云端请求 {result.calls} 次 · 自动采用 {result.accepted} 轮")
        self.issue_list.blockSignals(True)
        self.issue_list.clear()
        for issue in self.issues:
            self.issue_list.addItem(f"{issue.start_s:.2f}–{issue.end_s:.2f} 秒 · {KIND_TEXT[issue.kind]}")
        self.issue_list.setCurrentRow(0)
        self.issue_list.blockSignals(False)
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        self.candidate_list.addItems([c.title for c in self.candidates])
        self.candidate_list.blockSignals(False)
        self._candidate_changed()
        self.set_busy(self.busy)

    @property
    def candidate(self):
        index = self.candidate_list.currentIndex()
        return self.candidates[index] if index >= 0 else None

    def set_busy(self, busy):
        self.busy = busy
        self.candidate_panel.setVisible(bool(self.candidates))
        self.candidate_list.setEnabled(not busy)
        for button in self.track_buttons:
            button.setEnabled(not busy)
        self.prepare.setVisible(bool(self.issues) and not self.candidates)
        self.prepare.setEnabled(not busy)
        self.apply.setVisible(bool(self.candidates))
        self.apply.setEnabled(not busy and self.candidate is not None)
        self.locate.setEnabled(not busy and self.issue_list.currentRow() >= 0)
        self.restart.setEnabled(not busy and bool(self.current))
        self.export_button.setEnabled(not busy)
        self.close_button.setText("取消任务" if busy else "关闭")
        self._playback_state(self.player.playbackState())

    def set_status(self, text):
        self.status.setText(text)

    def _toggle_details(self, shown):
        self.details_toggle.setText("收起详情" if shown else "查看详情")
        self.details.setVisible(shown)

    def _refresh_details(self, *_):
        row = self.issue_list.currentRow()
        self.locate.setEnabled(not self.busy and row >= 0)
        text = []
        if row >= 0:
            issue = self.issues[row]
            text.extend(("所选疑点", issue.explanation))
            diagnostics = [e["summary"] for e in self.result.events if e["stage"] == "repair"
                           and e.get("start_s") == issue.start_s and e.get("end_s") == issue.end_s]
            text.extend(diagnostics[-1:])
        if self.candidate:
            text.extend(("", "候选改动", *note_changes(self.current, self.candidate.notes)))
        summaries = [e.get("summary", "") for e in self.result.events
                     if e["stage"] in ("compare", "error", "manual")]
        text.extend(("", *summaries))
        self.issue_detail.setPlainText("\n".join(text).strip() or "没有可定位的疑点。")

    def _candidate_changed(self, *_):
        self._clear_audio()
        if self.candidate:
            count = len(note_changes(self.current, self.candidate.notes))
            self.set_status(f"{count} 处音符变化 · 应用后可用 Ctrl+Z 撤销")
        elif self.issues:
            self.set_status("可在本地根据疑点生成候选。" if self.result.status != "manual"
                            else "可按原疑点检查剩余片段。")
        else:
            self.set_status("")
        self._refresh_details()

    def _locate(self):
        row = self.issue_list.currentRow()
        if not self.busy and row >= 0:
            self.locate_requested.emit(self.issues[row])

    def _apply(self):
        if not self.busy and self.candidate:
            self.apply_requested.emit(self.candidate)

    def _choose_track(self, index):
        if self.busy or self.candidate is None:
            return
        if not self.paths:
            self.track_buttons[index].setChecked(False)
            self.audition_requested.emit(self.candidate, index)
            return
        source = QUrl.fromLocalFile(str(self.paths[index]))
        self.resume_position = self.player.position()
        if self.resume_position >= self.timeline.maximum() - 50:
            self.resume_position = 0
        if self.player.source() != source:
            self.player.setSource(source)
        else:
            self.player.setPosition(self.resume_position)
        for i, button in enumerate(self.track_buttons):
            button.setChecked(i == index)
        self.player.play()
        self.set_status(f"试听{self.track_buttons[index].text()} · {self.first:.2f}–{self.last:.2f} 秒")

    def play_audition(self, value, index):
        self.paths, self.first, self.last = value
        self.timeline.setRange(0, round((self.last - self.first) * 1000))
        self._choose_track(index)

    def _clear_audio(self):
        self.paths = ()
        self.player.stop()
        self.player.setSource(QUrl())
        self.timeline.setRange(0, 0)
        self.timeline.setEnabled(False)
        for button in self.track_buttons:
            button.setChecked(False)

    def _loaded(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.player.setPosition(self.resume_position)
            self.timeline.setEnabled(True)

    def _position_changed(self, milliseconds):
        if not self.timeline.isSliderDown():
            self.timeline.setValue(milliseconds)

    def _playback_state(self, state):
        self.stop.setEnabled(not self.busy and state != QMediaPlayer.PlaybackState.StoppedState)

    def _playback_error(self, *_):
        self._clear_audio()
        self.set_status("试听失败，可重新选择音轨重试。")

    def reject(self):
        if self.busy:
            self.cancel_requested.emit()
        else:
            super().reject()

    def done(self, code):
        self._clear_audio()
        super().done(code)

    def export(self):
        selected, _ = QFileDialog.getSaveFileName(self, "导出复核记录", "音频复核.json", "JSON (*.json)")
        if selected:
            try:
                save_report(self.result, Path(selected))
            except (OSError, ValueError):
                self.set_status("无法保存复核记录，请选择可写入的位置。")
