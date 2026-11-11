"""Native desktop workspace, editor and transport controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QProgressBar, QScrollArea, QSlider, QSplitter, QTableWidget,
    QTabWidget, QVBoxLayout, QWidget, QPushButton,
)

from .export import PROGRAMS
from .score import BPM_MAX, BPM_MIN, KEYS
from .score_view import ScoreView

STYLE = """
QMainWindow { background: #f5f6f3; }
QWidget { color: #283532; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QFrame#sidebar { background: #23312e; border-radius: 12px; }
QFrame#sidebar QLabel { color: #afc1b9; background: transparent; }
QFrame#sidebar QLabel#brand { font-family: "Segoe UI"; font-size: 29px; font-weight: 600; color: #ffffff; }
QLabel#caption { color: #65746e; font-size: 12px; }
QLabel#heading { font-size: 26px; font-weight: 600; color: #202e29; }
QLabel#section { color: #65746e; font-size: 12px; }
QPushButton { background: white; border: 1px solid #dce2dc; border-radius: 7px; padding: 5px 13px; }
QPushButton:hover { background: #edf2ed; border-color: #a4b8ac; }
QPushButton:pressed { background: #dce8df; }
QPushButton#primary { background: #26715c; color: white; border-color: #26715c; font-weight: 600; padding: 5px 22px; }
QPushButton#primary:hover { background: #1b5d4a; }
QPushButton:disabled, QPushButton#primary:disabled { background: #f1f3ef; color: #9aa59e; border-color: #e7ebe4; }
QPushButton#quiet { border-color: transparent; background: transparent; color: #566a60; }
QPushButton#quiet:hover { background: #e7ede6; }
QPushButton#quiet:disabled { color: #a4ada6; }
QFrame#sidebar QPushButton { text-align: left; color: #e1e9e4; background: transparent; border: 1px solid transparent; padding-left: 14px; }
QFrame#sidebar QPushButton:hover { background: #34473e; }
QFrame#sidebar QPushButton#import { background: #3c5649; border-color: #56705e; color: white; font-weight: 600; }
QFrame#sidebar QPushButton:disabled { color: #7e9386; }
QPushButton:focus, QComboBox:focus, QDoubleSpinBox:focus, QTableWidget:focus, QListWidget:focus { border: 1px solid #26715c; }
QFrame#sidebar QPushButton:focus, QFrame#sidebar QListWidget:focus { border: 1px solid #afcfbc; }
QComboBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #dce2dc; border-radius: 6px; padding: 4px 8px; selection-background-color: #deebe2; selection-color: #203b2d; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: #9aa59e; background: #f3f5f0; }
QComboBox QAbstractItemView { background: white; color: #283532; selection-background-color: #deebe2; selection-color: #203b2d; }
QFrame#processing { background: #eef1eb; border: 1px solid #e1e7dd; border-radius: 9px; }
QFrame#player { background: #ffffff; border: 1px solid #e0e6dd; border-radius: 10px; }
QTabWidget::pane { border: 1px solid #e0e6dd; background: white; border-radius: 9px; top: -1px; }
QTabBar::tab { padding: 12px 20px; background: transparent; color: #758078; border-bottom: 2px solid transparent; margin-right: 12px; }
QTabBar::tab:selected { color: #245c46; border-bottom-color: #26715c; font-weight: 600; }
QTabBar::tab:hover { color: #245c46; }
QScrollArea, QTableWidget { border: 0; background: white; alternate-background-color: #f6f8f3; selection-background-color: #e0ece2; selection-color: #203b2d; }
QHeaderView::section { background: #f3f6f0; color: #66766a; border: 0; padding: 12px; }
QTableWidget::item { padding: 6px; border-bottom: 1px solid #f0f3ec; }
QFrame#sidebar QListWidget { background: transparent; color: #ccd9d0; border: 1px solid transparent; }
QListWidget::item { padding: 10px 8px; margin: 2px 0; border-radius: 5px; }
QListWidget::item:selected { background: #3c5649; color: white; }
QSlider::groove:horizontal { height: 4px; background: #e2e9df; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #43836a; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #26715c; border-radius: 6px; }
QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled { background: #b6c3b8; }
QProgressBar { border: 0; background: #e2e9df; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #43836a; }
QMenuBar { background: #f5f6f3; color: #65746e; padding: 3px 8px; }
QMenuBar::item:selected, QMenu::item:selected { background: #e0ece2; color: #203b2d; }
QMenu { background: white; padding: 6px; border: 1px solid #dce2dc; }
QMenu::item { padding: 7px 28px; }
QScrollBar:vertical { width: 8px; background: #f7f8f5; margin: 0; }
QScrollBar::handle:vertical { background: #cbd5c9; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #23312e; color: white; border: 0; padding: 6px; }
"""


def build_interface(w):
    w.setStyleSheet(STYLE)
    palette = w.palette()
    for role, color in ((QPalette.ColorRole.Base, "#ffffff"), (QPalette.ColorRole.Text, "#283532"),
                        (QPalette.ColorRole.Window, "#f5f6f3"), (QPalette.ColorRole.WindowText, "#283532"),
                        (QPalette.ColorRole.Highlight, "#e0ece2"), (QPalette.ColorRole.HighlightedText, "#203b2d")):
        palette.setColor(role, QColor(color))
    w.setPalette(palette)
    central = QWidget()
    w.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(20, 18, 20, 12)
    layout.setSpacing(12)
    split = QSplitter()
    layout.addWidget(split, 1)
    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(16, 26, 16, 20)
    side.setSpacing(10)
    brand = QLabel("NoteFlow")
    brand.setObjectName("brand")
    side.addWidget(brand)
    subtitle = QLabel("本地音乐制谱工作台")
    subtitle.setObjectName("caption")
    side.addWidget(subtitle)
    side.addSpacing(24)
    w.open_button = w._button(side, "导入音频或视频…", w.choose_source)
    w.open_button.setObjectName("import")
    w.open_project_button = w._button(side, "打开项目…", w.choose_project)
    w.save_button = w._button(side, "保存项目", w.save_project)
    side.addSpacing(14)
    recent_label = QLabel("最近项目")
    recent_label.setObjectName("section")
    side.addWidget(recent_label)
    w.recent = QListWidget()
    w.recent.setAccessibleName("最近项目")
    w.recent.itemDoubleClicked.connect(lambda item: w.open_source(item.data(Qt.ItemDataRole.UserRole)))
    side.addWidget(w.recent, 1)
    w.settings_button = w._button(side, "工具设置…", w.configure_tools)
    info = QLabel("WAV · MP3 · MP4 · M4A\n单段最长 120 秒 · 最大 200 MB")
    info.setObjectName("caption")
    info.setWordWrap(True)
    side.addWidget(info)
    sidebar.setMinimumWidth(210)
    sidebar.setMaximumWidth(260)
    split.addWidget(sidebar)

    content = QWidget()
    body = QVBoxLayout(content)
    body.setContentsMargins(24, 4, 0, 0)
    body.setSpacing(10)
    w.project_label = QLabel("新的音乐项目")
    w.project_label.setObjectName("heading")
    w.project_label.setTextFormat(Qt.TextFormat.PlainText)
    w.project_label.setWordWrap(True)
    body.addWidget(w.project_label)
    w.source_label = QLabel("导入一段音乐，开始识别和编辑。")
    w.source_label.setWordWrap(True)
    w.source_label.setTextFormat(Qt.TextFormat.PlainText)
    w.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    w.source_label.setObjectName("caption")
    body.addWidget(w.source_label)
    processing = QFrame()
    processing.setObjectName("processing")
    processing_layout = QVBoxLayout(processing)
    processing_layout.setContentsMargins(12, 10, 12, 10)
    pipeline = QHBoxLayout()
    w.source_mode = QComboBox()
    w.source_mode.addItems(("原曲 / 独奏", "分离人声"))
    w._field(pipeline, "识别来源", w.source_mode)
    w.separate_button = w._button(pipeline, "分离人声与伴奏", w.separate_tracks)
    pipeline.addStretch()
    w.generate_button = w._button(pipeline, "生成简谱", w.generate)
    w.generate_button.setObjectName("primary")
    w.cancel_button = w._button(pipeline, "取消任务", w.cancel_job)
    processing_layout.addLayout(pipeline)
    body.addWidget(processing)

    w.calibration_panel = QWidget()
    controls = QHBoxLayout(w.calibration_panel)
    controls.setContentsMargins(0, 0, 0, 0)
    w.bpm = QDoubleSpinBox()
    w.bpm.setRange(BPM_MIN, BPM_MAX)
    w.bpm.setDecimals(1)
    w.bpm.setValue(120)
    w.offset = QDoubleSpinBox()
    w.offset.setDecimals(3)
    w.offset.setSingleStep(0.01)
    w.key = QComboBox()
    w.key.addItems(KEYS)
    w._field(controls, "BPM", w.bpm)
    w._field(controls, "首拍 / 秒", w.offset)
    w._field(controls, "主音", w.key)
    w.apply_button = w._button(controls, "应用校准", w.apply_calibration)
    controls.addStretch()
    w.calibration_panel.setVisible(False)
    w.bpm.valueChanged.connect(w._update_offset_limit)
    w._update_offset_limit()
    body.addWidget(w.calibration_panel)
    w.tabs = QTabWidget()
    w.tabs.setMinimumHeight(210)
    w.calibration_toggle = QPushButton("节奏与调号  +")
    w.calibration_toggle.setMinimumHeight(36)
    w.calibration_toggle.setObjectName("quiet")
    w.calibration_toggle.setCheckable(True)
    w.calibration_toggle.toggled.connect(w.calibration_panel.setVisible)
    w.calibration_toggle.toggled.connect(lambda opened: w.calibration_toggle.setText("节奏与调号  −" if opened else "节奏与调号  +"))
    w.tabs.setCornerWidget(w.calibration_toggle, Qt.Corner.TopRightCorner)
    w.score_view = ScoreView()
    w.score_scroll = QScrollArea()
    w.score_scroll.setWidgetResizable(True)
    w.score_scroll.setWidget(w.score_view)
    w.score_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.tabs.addTab(w.score_scroll, "数字简谱")
    editor = QWidget()
    edit_layout = QVBoxLayout(editor)
    edit_layout.setContentsMargins(12, 12, 12, 12)
    edit_layout.setSpacing(8)
    edit_actions = QHBoxLayout()
    w.add_note_button = w._button(edit_actions, "添加", w.add_note)
    w.delete_note_button = w._button(edit_actions, "删除", w.delete_note)
    w.lower_button = w._button(edit_actions, "− 半音", lambda: w.transpose_note(-1))
    w.higher_button = w._button(edit_actions, "+ 半音", lambda: w.transpose_note(1))
    w.down_octave_button = w._button(edit_actions, "− 八度", lambda: w.transpose_note(-12))
    w.up_octave_button = w._button(edit_actions, "+ 八度", lambda: w.transpose_note(12))
    edit_layout.addLayout(edit_actions)
    w.note_table = QTableWidget(0, 5)
    w.note_table.setHorizontalHeaderLabels(("开始 / 秒", "结束 / 秒", "音高 / MIDI", "音名", "力度"))
    w.note_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    w.note_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.note_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.note_table.setAlternatingRowColors(True)
    w.note_table.setShowGrid(False)
    w.note_table.verticalHeader().setDefaultSectionSize(42)
    w.note_table.verticalHeader().setVisible(False)
    w.note_table.setMinimumHeight(120)
    w.note_table.setToolTip("双击单元格修改音符，选中行后可调整半音或八度。")
    w.note_table.setAccessibleName("旋律音符编辑")
    w.note_table.cellChanged.connect(w.edit_note)
    w.note_table.itemSelectionChanged.connect(w._note_selected)
    edit_layout.addWidget(w.note_table)
    w.tabs.addTab(editor, "音符编辑")
    body.addWidget(w.tabs, 1)
    exports = QHBoxLayout()
    w.undo_button = w._button(exports, "撤销", w.undo)
    w.redo_button = w._button(exports, "重做", w.redo)
    exports.addStretch()
    w.txt_button = w._button(exports, "导出 TXT…", lambda: w.export(False))
    w.midi_button = w._button(exports, "导出 MIDI…", lambda: w.export(True))
    w.audio_export_button = w._button(exports, "导出音频…", w.export_audio)
    body.addLayout(exports)
    split.addWidget(content)
    split.setStretchFactor(1, 1)
    split.setChildrenCollapsible(False)
    split.setSizes([220, 900])

    player = QFrame()
    player.setObjectName("player")
    player_layout = QVBoxLayout(player)
    player_layout.setContentsMargins(16, 10, 16, 10)
    player_layout.setSpacing(6)
    tracks = QHBoxLayout()
    w.original_button = w._button(tracks, "播放原曲", w.play_original)
    w.vocals_button = w._button(tracks, "播放人声", lambda: w.play_stem(vocals=True))
    w.accompaniment_button = w._button(tracks, "播放伴奏", lambda: w.play_stem(vocals=False))
    tracks.addStretch()
    w.instrument = QComboBox()
    w.instrument.addItems(PROGRAMS)
    w._field(tracks, "音色", w.instrument)
    w.melody_button = w._button(tracks, "试听旋律", lambda: w.play(original_timing=True))
    w.play_button = w._button(tracks, "播放简谱", w.play)
    w.instrument.currentIndexChanged.connect(w._change_instrument)
    player_layout.addLayout(tracks)
    transport = QHBoxLayout()
    w.pause_button = w._button(transport, "暂停", w.toggle_pause)
    w.stop_button = w._button(transport, "停止", w.stop_playback)
    w.timeline = QSlider(Qt.Orientation.Horizontal)
    w.timeline.setAccessibleName("播放进度")
    w.timeline.sliderReleased.connect(w.seek)
    transport.addWidget(w.timeline, 1)
    w.time_label = QLabel("00:00 / 00:00")
    w.time_label.setObjectName("caption")
    transport.addWidget(w.time_label)
    w.rate = QComboBox()
    w.rate.addItems(("0.5×", "0.75×", "1.0×", "1.25×", "1.5×"))
    w.rate.setCurrentIndex(2)
    w.rate.currentIndexChanged.connect(w.change_rate)
    w._field(transport, "速度", w.rate)
    w.volume = QSlider(Qt.Orientation.Horizontal)
    w.volume.setRange(0, 100)
    w.volume.setValue(65)
    w.volume.setMaximumWidth(90)
    w.volume.setAccessibleName("音量")
    w.volume.valueChanged.connect(lambda value: w._audio.setVolume(value / 100))
    transport.addWidget(QLabel("音量"))
    transport.addWidget(w.volume)
    player_layout.addLayout(transport)
    layout.addWidget(player)
    feedback = QHBoxLayout()
    w.status = QLabel("打开文件或将音频拖入窗口。")
    w.status.setTextFormat(Qt.TextFormat.PlainText)
    w.status.setWordWrap(True)
    w.status.setObjectName("caption")
    w.progress = QProgressBar()
    w.progress.setRange(0, 0)
    w.progress.setMaximumWidth(120)
    w.progress.setAccessibleName("后台任务进度")
    feedback.addWidget(w.status, 1)
    feedback.addWidget(w.progress)
    layout.addLayout(feedback)

    for button in (w.open_project_button, w.save_button, w.settings_button, w.undo_button, w.redo_button,
                   w.original_button, w.vocals_button, w.accompaniment_button, w.melody_button,
                   w.stop_button, w.pause_button, w.cancel_button):
        button.setObjectName("quiet")

    for button in w.findChildren(QPushButton):
        if button not in (w.open_button, w.generate_button):
            button.setMinimumHeight(36)
    for field in (w.bpm, w.offset, w.key, w.instrument, w.rate):
        field.setMinimumHeight(34)
    w.timeline.setMinimumHeight(22)
    w.volume.setMinimumHeight(22)

    menu = w.menuBar().addMenu("文件")
    for title, shortcut, action in (
        ("导入音频…", "Ctrl+O", w.choose_source), ("打开项目…", "Ctrl+Shift+O", w.choose_project),
        ("保存项目", "Ctrl+S", w.save_project), ("项目另存为…", "Ctrl+Shift+S", lambda: w.save_project(save_as=True)),
        ("退出", "Ctrl+Q", w.close),
    ):
        item = QAction(title, w)
        item.setShortcut(QKeySequence(shortcut))
        item.triggered.connect(action)
        menu.addAction(item)
    edit_menu = w.menuBar().addMenu("编辑")
    for title, shortcut, action in (("撤销", "Ctrl+Z", w.undo), ("重做", "Ctrl+Y", w.redo)):
        item = QAction(title, w)
        item.setShortcut(QKeySequence(shortcut))
        item.triggered.connect(action)
        edit_menu.addAction(item)
    help_menu = w.menuBar().addMenu("帮助")
    help_menu.addAction("使用说明", w.show_help)
    QShortcut(QKeySequence("Ctrl+G"), w, w.generate_button.click)
    QShortcut(QKeySequence("Escape"), w, w.cancel_button.click)
