"""Native desktop workspace, editor and transport controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QProgressBar, QScrollArea, QSlider, QSplitter, QTableWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from .export import PROGRAMS
from .score import BPM_MAX, BPM_MIN, KEYS
from .score_view import ScoreView

STYLE = """
QMainWindow { background: #f1f4f8; }
QWidget { color: #243449; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QFrame#sidebar { background: #e6edf5; border-radius: 12px; }
QLabel#brand { font-size: 26px; font-weight: 700; color: #1c3d61; }
QLabel#caption { color: #566b82; }
QLabel#heading { font-size: 20px; font-weight: 600; }
QPushButton { background: #ffffff; border: 1px solid #b4c3d4; border-radius: 6px; padding: 5px 12px; }
QPushButton:hover { background: #e7effa; border-color: #6286b1; }
QPushButton:pressed { background: #d1e1f4; }
QPushButton#primary { background: #255b98; color: white; border-color: #255b98; font-weight: 600; }
QPushButton#primary:hover { background: #194878; }
QPushButton:disabled { background: #eef1f5; color: #8a96a4; border-color: #d7dee7; }
QPushButton#primary:disabled { background: #eef1f5; color: #8a96a4; border-color: #d7dee7; }
QPushButton:focus, QComboBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTableWidget:focus { border: 2px solid #377cce; }
QComboBox, QDoubleSpinBox { background: white; border: 1px solid #b4c3d4; border-radius: 5px; padding: 4px; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: #8a96a4; background: #eef1f5; }
QTabWidget::pane { border: 1px solid #cad5e2; background: white; border-radius: 6px; }
QTabBar::tab { padding: 10px 22px; background: #e4ebf3; border: 1px solid #cad5e2; }
QTabBar::tab:selected { background: white; color: #255b98; font-weight: 600; }
QScrollArea, QTableWidget { border: 0; background: white; }
QHeaderView::section { background: #eef3f8; border: 0; padding: 10px; }
QListWidget { background: transparent; border: 0; }
QListWidget::item { padding: 9px 4px; border-bottom: 1px solid #d0dbe7; }
QListWidget::item:selected { background: #cbdcf0; color: #193d67; }
QSlider::groove:horizontal { height: 5px; background: #c4d2e3; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3979bd; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #255b98; border-radius: 7px; }
QProgressBar { border: 0; background: #dce7f3; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #3979bd; }
"""


def build_interface(w):
    w.setStyleSheet(STYLE)
    palette = w.palette()
    for role, color in ((QPalette.ColorRole.Base, "#ffffff"), (QPalette.ColorRole.Text, "#243449"),
                        (QPalette.ColorRole.Window, "#f1f4f8"), (QPalette.ColorRole.WindowText, "#243449"),
                        (QPalette.ColorRole.Highlight, "#d2e4f8"), (QPalette.ColorRole.HighlightedText, "#193d67")):
        palette.setColor(role, QColor(color))
    w.setPalette(palette)
    central = QWidget()
    w.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(18, 16, 18, 14)
    layout.setSpacing(12)
    split = QSplitter()
    layout.addWidget(split, 1)
    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    side = QVBoxLayout(sidebar)
    side.setContentsMargins(16, 18, 16, 16)
    side.setSpacing(10)
    brand = QLabel("NoteFlow")
    brand.setObjectName("brand")
    side.addWidget(brand)
    subtitle = QLabel("本地音乐制谱工作台")
    subtitle.setObjectName("caption")
    side.addWidget(subtitle)
    side.addSpacing(12)
    w.open_button = w._button(side, "导入音频或视频…", w.choose_source)
    w.open_project_button = w._button(side, "打开项目…", w.choose_project)
    w.save_button = w._button(side, "保存项目", w.save_project)
    side.addSpacing(14)
    side.addWidget(QLabel("最近项目"))
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
    body.setContentsMargins(16, 0, 0, 0)
    body.setSpacing(12)
    w.project_label = QLabel("新的音乐项目")
    w.project_label.setObjectName("heading")
    w.project_label.setTextFormat(Qt.TextFormat.PlainText)
    body.addWidget(w.project_label)
    w.source_label = QLabel("导入一段音乐，开始识别和编辑。")
    w.source_label.setWordWrap(True)
    w.source_label.setTextFormat(Qt.TextFormat.PlainText)
    w.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    w.source_label.setObjectName("caption")
    body.addWidget(w.source_label)
    pipeline = QHBoxLayout()
    w.source_mode = QComboBox()
    w.source_mode.addItems(("原曲 / 独奏", "分离人声"))
    w._field(pipeline, "识别来源", w.source_mode)
    w.separate_button = w._button(pipeline, "分离人声与伴奏", w.separate_tracks)
    w.generate_button = w._button(pipeline, "生成简谱", w.generate)
    w.generate_button.setObjectName("primary")
    w.cancel_button = w._button(pipeline, "取消任务", w.cancel_job)
    pipeline.addStretch()
    body.addLayout(pipeline)

    controls = QHBoxLayout()
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
    body.addLayout(controls)
    w.bpm.valueChanged.connect(w._update_offset_limit)
    w._update_offset_limit()
    w.tabs = QTabWidget()
    w.score_view = ScoreView()
    w.score_scroll = QScrollArea()
    w.score_scroll.setWidgetResizable(True)
    w.score_scroll.setWidget(w.score_view)
    w.score_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.tabs.addTab(w.score_scroll, "数字简谱")
    editor = QWidget()
    edit_layout = QVBoxLayout(editor)
    help_text = QLabel("双击单元格修改音符。选中音符后可调整半音或八度。")
    help_text.setWordWrap(True)
    edit_layout.addWidget(help_text)
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
    layout.addLayout(tracks)
    transport = QHBoxLayout()
    w.pause_button = w._button(transport, "暂停", w.toggle_pause)
    w.stop_button = w._button(transport, "停止", w.stop_playback)
    w.timeline = QSlider(Qt.Orientation.Horizontal)
    w.timeline.setAccessibleName("播放进度")
    w.timeline.sliderReleased.connect(w.seek)
    transport.addWidget(w.timeline, 1)
    w.time_label = QLabel("00:00 / 00:00")
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
    layout.addLayout(transport)
    feedback = QHBoxLayout()
    w.status = QLabel("打开文件或将音频拖入窗口。")
    w.status.setTextFormat(Qt.TextFormat.PlainText)
    w.status.setWordWrap(True)
    w.progress = QProgressBar()
    w.progress.setRange(0, 0)
    w.progress.setMaximumWidth(120)
    w.progress.setAccessibleName("后台任务进度")
    feedback.addWidget(w.status, 1)
    feedback.addWidget(w.progress)
    layout.addLayout(feedback)

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
