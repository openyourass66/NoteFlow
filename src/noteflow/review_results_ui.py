"""Turn review feedback into navigation, local proposals and reversible edits."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QPushButton, QSlider, QVBoxLayout,
)

from .review import RepairCandidate, ReviewIssue, STATUS_TEXT, fingerprint
from .review_edit import latest_issues, note_changes

KIND_TEXT = {"pitch": "音高", "octave": "八度", "rhythm": "节奏", "fragmentation": "连贯性",
             "wrong_voice": "声部", "missing_notes": "漏音"}


@dataclass(frozen=True, slots=True)
class ReviewAction:
    kind: str
    issues: tuple[ReviewIssue, ...] = ()
    candidate: RepairCandidate | None = None


class ReviewReportDialog(QDialog):
    def __init__(self, parent, result, report_path, current_notes):
        super().__init__(parent)
        self.result, self.report_path, self.current = result, report_path, current_notes
        self.action = None
        self.issues = latest_issues(result)
        self.setWindowTitle("复核结果与乐谱修改")
        self.resize(800, 640)
        layout = QVBoxLayout(self)
        header = QLabel(STATUS_TEXT[result.status] +
                        f"\n范围 {result.start_s:.2f}–{result.end_s:.2f} 秒 · 请求 {result.calls} 次 · 自动采用 {result.accepted} 轮")
        header.setTextFormat(Qt.TextFormat.PlainText)
        header.setWordWrap(True)
        layout.addWidget(header)
        self.notice = QLabel("以下是最近一轮的疑点。可定位编辑，或在本地重建候选后试听、应用；云端意见可能有误。")
        if fingerprint(current_notes) != fingerprint(result.notes):
            self.notice.setText("当前乐谱已变化：旧候选不能直接应用。可按原疑点重新生成候选，再对照试听。")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        self.issue_list = QListWidget()
        self.issue_list.setAccessibleName("复核疑点列表")
        self.issue_list.setMinimumWidth(210)
        self.issue_list.setMaximumWidth(275)
        for issue in self.issues:
            self.issue_list.addItem(f"{issue.start_s:.2f}–{issue.end_s:.2f} 秒 · {KIND_TEXT[issue.kind]}")
        row.addWidget(self.issue_list)
        self.issue_detail = QPlainTextEdit()
        self.issue_detail.setReadOnly(True)
        self.issue_detail.setAccessibleName("问题与本地处理原因")
        row.addWidget(self.issue_detail, 1)
        layout.addLayout(row, 2)
        actions = QHBoxLayout()
        self.locate = QPushButton("定位到音符编辑")
        self.prepare = QPushButton("重建所选片段")
        self.prepare_all = QPushButton("生成全部局部候选")
        for button in (self.locate, self.prepare, self.prepare_all):
            button.setMinimumHeight(36)
            actions.addWidget(button)
        self.locate.clicked.connect(lambda: self.choose("locate", selected=True))
        self.prepare.clicked.connect(lambda: self.choose("prepare", selected=True))
        self.prepare_all.clicked.connect(lambda: self.choose("prepare"))
        layout.addLayout(actions)
        layout.addWidget(QLabel("候选修改（尚未自动采用）"))
        self.candidate_list = QComboBox()
        self.candidate_list.setAccessibleName("局部修改候选")
        self.candidate_list.setMinimumHeight(36)
        for candidate in result.candidates:
            self.candidate_list.addItem(candidate.title)
        layout.addWidget(self.candidate_list)
        self.changes = QPlainTextEdit()
        self.changes.setReadOnly(True)
        self.changes.setAccessibleName("候选音符改动明细")
        layout.addWidget(self.changes, 2)
        candidate_actions = QHBoxLayout()
        self.preview = QPushButton("对照试听原曲／修改前／候选…")
        self.apply = QPushButton("应用所选候选")
        self.apply.setObjectName("primary")
        for button in (self.preview, self.apply):
            button.setMinimumHeight(36)
            candidate_actions.addWidget(button)
        self.preview.clicked.connect(lambda: self.choose("preview"))
        self.apply.clicked.connect(lambda: self.choose("apply"))
        layout.addLayout(candidate_actions)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        export = buttons.addButton("导出记录…", QDialogButtonBox.ButtonRole.ActionRole)
        export.clicked.connect(self.export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.issue_list.currentRowChanged.connect(self.refresh_issue)
        self.candidate_list.currentIndexChanged.connect(self.refresh_candidate)
        self.issue_list.setCurrentRow(0)
        self.refresh_issue()
        self.refresh_candidate()

    def refresh_issue(self, *_):
        index = self.issue_list.currentRow()
        selected = 0 <= index < len(self.issues)
        self.locate.setEnabled(selected)
        self.prepare.setEnabled(selected)
        self.prepare_all.setEnabled(bool(self.issues))
        text = []
        if selected:
            issue = self.issues[index]
            text += ["云端反馈：", issue.explanation, "", "本地处理："]
            diagnostics = [e["summary"] for e in self.result.events if e["stage"] == "repair"
                           and e.get("start_s") == issue.start_s and e.get("end_s") == issue.end_s]
            text += diagnostics[-2:] or ["暂无局部重建记录。点击下方按钮可生成候选，不会再次上传音频。"]
        else:
            text.append("没有可定位的疑点。")
        for event in self.result.events:
            if event["stage"] in ("compare", "error", "manual"):
                text.extend(("", event.get("summary", "")))
        self.issue_detail.setPlainText("\n".join(text))

    def refresh_candidate(self, *_):
        index = self.candidate_list.currentIndex()
        candidate = self.result.candidates[index] if 0 <= index < len(self.result.candidates) else None
        valid = candidate is not None and candidate.baseline_fingerprint == fingerprint(self.current)
        self.preview.setEnabled(valid)
        self.apply.setEnabled(valid)
        if candidate is None:
            self.changes.setPlainText("尚无候选修改。请先重建疑点片段；也可以直接定位音符手动编辑。")
        elif not valid:
            self.changes.setPlainText("此候选对应旧版乐谱，请重新生成。")
        else:
            self.changes.setPlainText("应用后简谱与演奏一起更新，可用 Ctrl+Z 撤销；这不代表云端复核通过。\n\n" +
                                      "\n".join(note_changes(self.current, candidate.notes)))

    def choose(self, kind, selected=False):
        issues = self.issues
        if selected:
            index = self.issue_list.currentRow()
            if not 0 <= index < len(issues):
                return
            issues = (issues[index],)
        candidate = None
        if kind in ("apply", "preview"):
            index = self.candidate_list.currentIndex()
            if not 0 <= index < len(self.result.candidates):
                return
            candidate = self.result.candidates[index]
            if candidate.baseline_fingerprint != fingerprint(self.current):
                return
        self.action = ReviewAction(kind, issues, candidate)
        self.accept()

    def export(self):
        selected, _ = QFileDialog.getSaveFileName(self, "导出复核记录", "音频复核.json", "JSON (*.json)")
        if selected:
            try:
                Path(selected).write_bytes(Path(self.report_path).read_bytes())
            except OSError:
                self.error.setText("无法保存复核记录，请选择可写入的位置。")


class CandidateAuditionDialog(QDialog):
    def __init__(self, parent, paths, first, last):
        super().__init__(parent)
        self.paths = paths
        self.setWindowTitle("局部修改对照试听")
        self.resize(580, 225)
        layout = QVBoxLayout(self)
        label = QLabel(f"试听原曲 {first:.2f}–{last:.2f} 秒\n三个音轨使用相同起止时间。切换时保留位置；关闭窗口不会改谱。")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.output = QAudioOutput(self)
        self.output.setVolume(.65)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        tracks = QHBoxLayout()
        self.track_buttons = []
        for index, name in enumerate(("原曲", "修改前", "候选")):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _=False, i=index: self.play_track(i))
            self.track_buttons.append(button)
            tracks.addWidget(button)
        stop = QPushButton("停止")
        stop.clicked.connect(self.player.stop)
        tracks.addWidget(stop)
        layout.addLayout(tracks)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setAccessibleName("候选对照播放进度")
        self.timeline.setRange(0, round((last - first) * 1000))
        self.timeline.sliderReleased.connect(lambda: self.player.setPosition(self.timeline.value()))
        layout.addWidget(self.timeline)
        self.status = QLabel("请选择音轨开始试听。")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.player.positionChanged.connect(lambda ms: self.timeline.setValue(ms) if not self.timeline.isSliderDown() else None)
        self.player.errorOccurred.connect(lambda *_: self.status.setText("播放失败，请检查系统音频输出；未改动乐谱。"))
        self.resume_position = 0
        self.player.mediaStatusChanged.connect(self.loaded)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("返回结果")
        apply = buttons.addButton("应用候选到简谱", QDialogButtonBox.ButtonRole.AcceptRole)
        apply.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def play_track(self, index):
        self.resume_position = self.player.position()
        if self.resume_position >= self.timeline.maximum() - 50:
            self.resume_position = 0
        self.player.stop()
        for i, button in enumerate(self.track_buttons):
            button.setChecked(i == index)
        self.status.setText(f"正在试听{self.track_buttons[index].text()}；乐谱尚未改动。")
        source = QUrl.fromLocalFile(str(self.paths[index]))
        if self.player.source() == source:
            self.player.setPosition(self.resume_position)
        else:
            self.player.setSource(source)
        self.player.play()

    def loaded(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.player.setPosition(self.resume_position)

    def done(self, code):
        self.player.stop()
        self.player.setSource(QUrl())
        super().done(code)
