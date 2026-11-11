"""Native desktop workspace, editor and transport controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QMenu, QProgressBar, QPushButton, QScrollArea, QSlider, QStackedWidget,
    QTabBar, QTableWidget, QVBoxLayout, QWidget,
)

from .export import PROGRAMS
from .media import MAX_BYTES, MAX_SECONDS, MEDIA_SUFFIXES
from .score import BPM_MAX, BPM_MIN, KEYS
from .score_view import ScoreView

STYLE = """
QMainWindow { background: #f1f4f6; }
QWidget { color: #22323c; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QLabel#caption { color: #566773; font-size: 12px; }
QFrame#surface { background: white; border: 1px solid #dbe2e7; border-radius: 9px; }
QFrame#divider { background: #e2e8ec; }
QWidget#calibration { background: #f5f8f9; }
QPushButton {
    background: white; border: 1px solid #d4dee4; border-radius: 6px; padding: 0 11px;
}
QPushButton:hover { background: #f0f5f6; border-color: #a8bbc4; }
QPushButton:pressed { background: #e2ebed; }
QPushButton#quiet { border-color: transparent; background: transparent; }
QPushButton#quiet:hover { background: #e8eef1; }
QPushButton#quiet:pressed { background: #dce8eb; }
QPushButton#quiet:checked { background: #e3eeea; color: #1b5747; }
QPushButton#primary {
    background: #216451; border-color: #216451; color: white; font-weight: 600; padding: 0 16px;
}
QPushButton#primary:hover { background: #184e40; }
QPushButton#primary:pressed { background: #123e33; }
QPushButton#primary:focus { border: 2px solid #0f322a; }
QPushButton:disabled, QPushButton#primary:disabled {
    background: #f3f6f7; color: #82919a; border-color: #e3e9ed;
}
QPushButton#quiet:disabled { color: #82919a; }
QPushButton#more { font-family: "Segoe UI"; font-size: 20px; padding: 0; }
QPushButton#more::menu-indicator { image: none; width: 0; }
QPushButton#export { padding-right: 22px; }
QPushButton#export::menu-indicator { subcontrol-position: right center; right: 8px; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: #82919a; }
QComboBox QAbstractItemView {
    background: white; color: #22323c; selection-background-color: #dceee6; selection-color: #19483b;
}
QPushButton:focus, QPushButton#quiet:focus, QScrollArea:focus, QTableWidget:focus {
    border: 1px solid #216451;
}
QTabBar::tab {
    padding: 0 14px; min-height: 37px; background: transparent; color: #566773;
    border: 1px solid transparent; border-bottom-width: 2px;
}
QTabBar::tab:selected { color: #1b5747; border-bottom-color: #216451; font-weight: 600; }
QTabBar::tab:hover { background: #f0f5f6; }
QTabBar::tab:focus { border-color: #216451; }
QScrollArea, QTableWidget {
    border: 1px solid transparent; background: white; alternate-background-color: #f5f8f9;
    selection-background-color: #dceee6; selection-color: #19483b;
}
QHeaderView::section { background: #f1f4f6; color: #566773; border: 0; padding: 9px; }
QTableWidget::item { padding: 6px; border-bottom: 1px solid #edf1f3; }
QSlider::groove:horizontal { height: 4px; background: #dfe7eb; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #45806f; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #216451; border-radius: 6px; }
QSlider::handle:horizontal:focus { background: #216451; border: 2px solid #102e28; }
QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled { background: #aebcc4; }
QProgressBar { border: 0; background: #dfe7eb; border-radius: 3px; }
QProgressBar::chunk { background: #45806f; }
QMenu { background: white; padding: 4px; border: 1px solid #d4dee4; }
QMenu::item { padding: 7px 24px; border-radius: 4px; }
QMenu::item:selected { background: #e3eeea; color: #19483b; }
QMenu::item:disabled { color: #82919a; }
QMenu::separator { background: #e2e8ec; height: 1px; margin: 4px 8px; }
QScrollBar:vertical { width: 9px; background: #f5f8f9; margin: 0; }
QScrollBar::handle:vertical { background: #bfcbd2; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #22323c; color: white; border: 0; padding: 6px; }
"""


def _button(layout, text, action=None, *, style="", height=34):
    button = QPushButton(text)
    button.setMinimumHeight(height)
    button.setObjectName(style)
    if action is not None:
        button.clicked.connect(action)
    layout.addWidget(button)
    return button


def _field(layout, text, widget):
    label = QLabel(text)
    label.setBuddy(widget)
    label.setObjectName("caption")
    widget.setMinimumHeight(32)
    widget.setAccessibleName(text)
    layout.addWidget(label)
    layout.addWidget(widget)


def _divider(orientation):
    line = QFrame()
    line.setObjectName("divider")
    if orientation == Qt.Orientation.Horizontal:
        line.setFixedHeight(1)
    else:
        line.setFixedSize(1, 18)
    return line


def _menu_action(w, menu, title, action, shortcut):
    item = QAction(title, w)
    item.setShortcut(QKeySequence(shortcut))
    item.triggered.connect(action)
    w.addAction(item)
    menu.addAction(item)
    return item


def _workflow_toolbar(w):
    toolbar = QHBoxLayout()
    toolbar.setSpacing(6)
    w.open_button = _button(toolbar, "导入媒体…", w.choose_source)
    formats = " · ".join(suffix[1:].upper() for suffix in MEDIA_SUFFIXES)
    w.open_button.setToolTip(
        f"导入音频或视频 (Ctrl+O)\n{formats} · 最长 {MAX_SECONDS} 秒 · 最大 {MAX_BYTES // 1_000_000} MB"
    )
    w.open_project_button = _button(toolbar, "打开项目…", w.choose_project, style="quiet")
    w.save_button = _button(toolbar, "保存项目", w.save_project, style="quiet")
    toolbar.addStretch()
    w.source_mode = QComboBox()
    w.source_mode.addItems(("原曲 / 独奏", "分离人声"))
    _field(toolbar, "识别来源", w.source_mode)
    w.separate_button = _button(toolbar, "分离人声与伴奏", w.separate_tracks, style="quiet")
    w.generate_button = _button(toolbar, "生成简谱", w.generate, style="primary")
    w.cancel_button = _button(toolbar, "取消任务", w.cancel_job)
    toolbar.addSpacing(4)
    more = _button(toolbar, "⋯", style="more")
    more.setFixedWidth(36)
    more.setAccessibleName("更多操作")
    more.setToolTip("更多操作")
    menu = QMenu(more)
    w.recent_menu = menu.addMenu("最近项目")
    w.recent_menu.setToolTipsVisible(True)
    w.save_as_action = _menu_action(w, menu, "项目另存为…", lambda: w.save_project(save_as=True), "Ctrl+Shift+S")
    menu.addSeparator()
    w.settings_action = menu.addAction("工具设置…", w.configure_tools)
    menu.addAction("使用说明", w.show_help)
    _menu_action(w, menu, "退出", w.close, "Ctrl+Q")
    more.setMenu(menu)
    return toolbar


def _score_workspace(w):
    surface = QFrame()
    surface.setObjectName("surface")
    workspace = QVBoxLayout(surface)
    workspace.setContentsMargins(1, 1, 1, 4)
    workspace.setSpacing(0)
    tools = QHBoxLayout()
    tools.setContentsMargins(10, 2, 10, 0)
    tools.setSpacing(6)
    w.tabs = QTabBar()
    w.tabs.setExpanding(False)
    w.tabs.setDrawBase(False)
    w.tabs.setAccessibleName("制谱视图")
    w.tabs.addTab("数字简谱")
    w.tabs.addTab("音符编辑")
    tools.addWidget(w.tabs)
    tools.addStretch()
    w.undo_button = _button(tools, "撤销", w.undo, style="quiet", height=30)
    w.redo_button = _button(tools, "重做", w.redo, style="quiet", height=30)
    tools.addWidget(_divider(Qt.Orientation.Vertical))
    w.calibration_toggle = _button(tools, "节奏与调号  +", style="quiet", height=30)
    w.calibration_toggle.setAccessibleName("节奏与调号")
    w.calibration_toggle.setCheckable(True)
    w.export_button = _button(tools, "导出", style="export", height=30)
    menu = QMenu(w.export_button)
    w.txt_action = menu.addAction("导出 TXT…", lambda: w.export(False))
    w.midi_action = menu.addAction("导出 MIDI…", lambda: w.export(True))
    w.audio_export_action = menu.addAction("导出音频…", w.export_audio)
    w.export_button.setMenu(menu)
    workspace.addLayout(tools)
    workspace.addWidget(_divider(Qt.Orientation.Horizontal))

    calibration = QWidget()
    calibration.setObjectName("calibration")
    controls = QHBoxLayout(calibration)
    controls.setContentsMargins(16, 8, 16, 8)
    controls.setSpacing(8)
    w.bpm = QDoubleSpinBox()
    w.bpm.setRange(BPM_MIN, BPM_MAX)
    w.bpm.setDecimals(1)
    w.bpm.setValue(120)
    w.offset = QDoubleSpinBox()
    w.offset.setDecimals(3)
    w.offset.setSingleStep(0.01)
    w.key = QComboBox()
    w.key.addItems(KEYS)
    _field(controls, "BPM", w.bpm)
    _field(controls, "首拍 / 秒", w.offset)
    _field(controls, "主音", w.key)
    w.apply_button = _button(controls, "应用校准", w.apply_calibration, height=32)
    controls.addStretch()
    calibration.hide()
    w.bpm.valueChanged.connect(w._update_offset_limit)
    w._update_offset_limit()
    w.calibration_toggle.toggled.connect(calibration.setVisible)
    w.calibration_toggle.toggled.connect(
        lambda opened: w.calibration_toggle.setText("节奏与调号  −" if opened else "节奏与调号  +")
    )
    workspace.addWidget(calibration)

    w.score_view = ScoreView()
    w.score_scroll = QScrollArea()
    w.score_scroll.setWidgetResizable(True)
    w.score_scroll.setWidget(w.score_view)
    w.score_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    pages = QStackedWidget()
    pages.addWidget(w.score_scroll)
    pages.addWidget(_note_editor(w))
    w.tabs.currentChanged.connect(pages.setCurrentIndex)
    workspace.addWidget(pages, 1)
    return surface


def _note_editor(w):
    editor = QWidget()
    edit_layout = QVBoxLayout(editor)
    edit_layout.setContentsMargins(12, 12, 12, 12)
    edit_layout.setSpacing(8)
    edit_actions = QHBoxLayout()
    w.add_note_button = _button(edit_actions, "添加", w.add_note)
    w.delete_note_button = _button(edit_actions, "删除", w.delete_note)
    w.lower_button = _button(edit_actions, "− 半音", lambda: w.transpose_note(-1))
    w.higher_button = _button(edit_actions, "+ 半音", lambda: w.transpose_note(1))
    w.down_octave_button = _button(edit_actions, "− 八度", lambda: w.transpose_note(-12))
    w.up_octave_button = _button(edit_actions, "+ 八度", lambda: w.transpose_note(12))
    edit_actions.addStretch()
    edit_layout.addLayout(edit_actions)
    w.note_table = QTableWidget(0, 5)
    w.note_table.setHorizontalHeaderLabels(("开始 / 秒", "结束 / 秒", "音高 / MIDI", "音名", "力度"))
    w.note_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    w.note_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.note_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.note_table.setAlternatingRowColors(True)
    w.note_table.setShowGrid(False)
    w.note_table.verticalHeader().setDefaultSectionSize(36)
    w.note_table.verticalHeader().setVisible(False)
    w.note_table.setMinimumHeight(120)
    w.note_table.setToolTip("双击单元格修改音符，选中行后可调整半音或八度。")
    w.note_table.setAccessibleName("旋律音符编辑")
    w.note_table.cellChanged.connect(w.edit_note)
    w.note_table.itemSelectionChanged.connect(w._note_selected)
    edit_layout.addWidget(w.note_table)
    return editor


def _player(w):
    player = QFrame()
    player.setObjectName("surface")
    layout = QVBoxLayout(player)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.setSpacing(5)
    tracks = QHBoxLayout()
    tracks.setSpacing(6)
    w.original_button = _button(tracks, "播放原曲", w.play_original, style="quiet")
    w.vocals_button = _button(tracks, "播放人声", lambda: w.play_stem(vocals=True), style="quiet")
    w.accompaniment_button = _button(tracks, "播放伴奏", lambda: w.play_stem(vocals=False), style="quiet")
    tracks.addStretch()
    w.instrument = QComboBox()
    w.instrument.addItems(PROGRAMS)
    _field(tracks, "音色", w.instrument)
    w.melody_button = _button(tracks, "试听旋律", lambda: w.play(original_timing=True), style="quiet")
    w.play_button = _button(tracks, "播放简谱", w.play)
    w.instrument.currentIndexChanged.connect(w._change_instrument)
    layout.addLayout(tracks)
    layout.addWidget(_divider(Qt.Orientation.Horizontal))
    transport = QHBoxLayout()
    transport.setSpacing(6)
    w.pause_button = _button(transport, "暂停", w.toggle_pause, style="quiet", height=32)
    w.stop_button = _button(transport, "停止", w.stop_playback, style="quiet", height=32)
    w.timeline = QSlider(Qt.Orientation.Horizontal)
    w.timeline.setMinimumHeight(24)
    w.timeline.setAccessibleName("播放进度")
    w.timeline.sliderReleased.connect(w.seek)
    transport.addWidget(w.timeline, 1)
    w.time_label = QLabel("00:00 / 00:00")
    w.time_label.setObjectName("caption")
    transport.addWidget(w.time_label)
    transport.addSpacing(8)
    w.rate = QComboBox()
    w.rate.addItems(("0.5×", "0.75×", "1.0×", "1.25×", "1.5×"))
    w.rate.setCurrentIndex(2)
    w.rate.currentIndexChanged.connect(w.change_rate)
    _field(transport, "速度", w.rate)
    transport.addSpacing(8)
    w.volume = QSlider(Qt.Orientation.Horizontal)
    w.volume.setRange(0, 100)
    w.volume.setValue(65)
    w.volume.setFixedWidth(80)
    w.volume.valueChanged.connect(lambda value: w._audio.setVolume(value / 100))
    _field(transport, "音量", w.volume)
    layout.addLayout(transport)
    return player


def build_interface(w):
    w.setStyleSheet(STYLE)
    palette = w.palette()
    for role, color in ((QPalette.ColorRole.Base, "#ffffff"), (QPalette.ColorRole.Text, "#22323c"),
                        (QPalette.ColorRole.Window, "#f1f4f6"), (QPalette.ColorRole.WindowText, "#22323c"),
                        (QPalette.ColorRole.Button, "#ffffff"),
                        (QPalette.ColorRole.Highlight, "#dceee6"), (QPalette.ColorRole.HighlightedText, "#19483b")):
        palette.setColor(role, QColor(color))
    w.setPalette(palette)
    central = QWidget()
    w.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(16, 12, 16, 8)
    layout.setSpacing(10)
    layout.addLayout(_workflow_toolbar(w))
    layout.addWidget(_score_workspace(w), 1)
    layout.addWidget(_player(w))

    feedback = QHBoxLayout()
    w.status = QLabel()
    w.status.setTextFormat(Qt.TextFormat.PlainText)
    w.status.setWordWrap(True)
    w.status.setObjectName("caption")
    w.status.setMinimumHeight(18)
    w.progress = QProgressBar()
    w.progress.setRange(0, 0)
    w.progress.setTextVisible(False)
    w.progress.setFixedSize(96, 6)
    w.progress.setAccessibleName("后台任务进度")
    w.source_label = QLabel()
    w.source_label.setObjectName("caption")
    w.source_label.hide()
    feedback.addWidget(w.status, 1)
    feedback.addWidget(w.progress)
    feedback.addWidget(w.source_label)
    layout.addLayout(feedback)

    for shortcut, button in (("Ctrl+O", w.open_button), ("Ctrl+Shift+O", w.open_project_button),
                             ("Ctrl+S", w.save_button), ("Ctrl+G", w.generate_button),
                             ("Ctrl+Z", w.undo_button), ("Ctrl+Y", w.redo_button), ("Escape", w.cancel_button)):
        QShortcut(QKeySequence(shortcut), w, button.click)
        if not button.toolTip():
            button.setToolTip(shortcut)
    for shortcut in ("Ctrl+Tab", "Ctrl+Shift+Tab"):
        QShortcut(QKeySequence(shortcut), w, lambda: w.tabs.setCurrentIndex(1 - w.tabs.currentIndex()))
