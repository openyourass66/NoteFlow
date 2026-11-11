"""Native desktop workspace, editor and transport controls."""

from math import exp, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QLinearGradient, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QMenu, QProgressBar, QPushButton, QScrollArea, QSlider, QStackedWidget,
    QTabBar, QTableWidget, QVBoxLayout, QWidget,
)

from .desktop_theme import COLORS, ICON_SIZE, ComboBox, apply_theme, icon
from .export import PROGRAMS
from .media import MEDIA_SUFFIXES
from .score import BPM_MAX, BPM_MIN, KEYS
from .score_view import ScoreView

def _button(layout, text, action=None, *, style="", height=32, glyph=None):
    button = QPushButton(text)
    button.setMinimumHeight(height)
    button.setObjectName(style)
    if glyph:
        button.setIcon(icon(glyph, accent_ink=style == "primary"))
        button.setIconSize(ICON_SIZE)
    if action is not None:
        button.clicked.connect(action)
    layout.addWidget(button)
    return button


def _icon_button(layout, glyph, label, action=None):
    button = _button(layout, "", action, style="icon", glyph=glyph)
    button.setFixedWidth(32)
    button.setAccessibleName(label)
    button.setToolTip(label)
    return button


def set_transport_paused(button, paused):
    label = "继续播放" if paused else "暂停播放"
    button.setIcon(icon("play" if paused else "pause"))
    button.setAccessibleName(label)
    button.setToolTip(label)


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
    bar = QFrame()
    bar.setObjectName("toolbar")
    toolbar = QHBoxLayout(bar)
    toolbar.setContentsMargins(12, 6, 12, 6)
    toolbar.setSpacing(6)
    w.workflow_actions = QWidget()
    actions = QHBoxLayout(w.workflow_actions)
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(4)
    w.open_button = _icon_button(actions, "import", "导入媒体 · Ctrl+O", w.choose_source)
    w.open_project_button = _icon_button(actions, "folder", "打开项目 · Ctrl+Shift+O", w.choose_project)
    w.save_button = _icon_button(actions, "save", "保存项目 · Ctrl+S", w.save_project)
    actions.addStretch()
    w.source_mode = ComboBox()
    w.source_mode.addItem("自动", "auto")
    w.source_mode.addItem("原曲 / 独奏", "original")
    w.source_mode.addItem("分离人声", "vocals")
    _field(actions, "识别来源", w.source_mode)
    w.separate_button = _button(actions, "分离人声与伴奏", w.separate_tracks)
    w.generate_button = _button(actions, "生成简谱", w.generate, style="primary")
    toolbar.addWidget(w.workflow_actions, 1)
    w.toolbar_spacer = QWidget()
    toolbar.addWidget(w.toolbar_spacer, 1)
    w.cancel_button = _button(toolbar, "取消任务", w.cancel_job, style="quiet")
    more = _icon_button(toolbar, "more", "更多操作")
    menu = QMenu(more)
    w.recent_menu = menu.addMenu("最近项目")
    w.recent_menu.setToolTipsVisible(True)
    w.save_as_action = _menu_action(w, menu, "项目另存为…", lambda: w.save_project(save_as=True), "Ctrl+Shift+S")
    menu.addSeparator()
    w.settings_action = menu.addAction("工具设置…", w.configure_tools)
    menu.addAction("使用说明", w.show_help)
    _menu_action(w, menu, "退出", w.close, "Ctrl+Q")
    more.setMenu(menu)
    return bar


class _WelcomeWaveform(QWidget):
    """Decorative waveform for the media import card."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(118)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        tint = QLinearGradient(rect.topLeft(), rect.bottomRight())
        tint.setColorAt(0, QColor("#222943"))
        tint.setColorAt(1, QColor("#28243a"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawRoundedRect(rect, 9, 9)
        center = rect.center().y()
        painter.setPen(QColor("#3a4260"))
        painter.drawLine(QPointF(16, center), QPointF(rect.right() - 16, center))
        count = 75
        for index in range(count):
            ratio = index / (count - 1)
            x = 18 + (rect.width() - 36) * ratio
            envelope = exp(-((ratio - .30) / .17) ** 2) + .70 * exp(-((ratio - .70) / .12) ** 2)
            amplitude = 2 + 38 * envelope * (.22 + .78 * abs(sin(index * 1.63)))
            color = QColor(COLORS["accent"])
            color.setAlpha(65 + int(140 * min(1, envelope)))
            painter.setPen(QPen(QBrush(color), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x, center - amplitude), QPointF(x, center + amplitude))


def _start_page(w):
    page = QWidget()
    page.setObjectName("startPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.addStretch(4)
    card = QFrame()
    card.setObjectName("startCard")
    card.setFixedWidth(518)
    content = QVBoxLayout(card)
    content.setContentsMargins(24, 24, 24, 24)
    content.setSpacing(8)
    content.addWidget(_WelcomeWaveform())
    content.addSpacing(8)
    title = QLabel("从音频生成简谱")
    title.setObjectName("startTitle")
    content.addWidget(title)
    hint = QLabel("将音频或视频拖入窗口")
    hint.setObjectName("hint")
    content.addWidget(hint)
    content.addSpacing(7)
    actions = QHBoxLayout()
    actions.setSpacing(8)
    w.start_import = _button(actions, "导入媒体", w.choose_source, style="primary", height=38, glyph="import")
    w.start_open_project = _button(actions, "打开项目", w.choose_project, height=38, glyph="folder")
    actions.addStretch()
    content.addLayout(actions)
    formats = QLabel(" · ".join(suffix[1:].upper() for suffix in MEDIA_SUFFIXES))
    formats.setObjectName("caption")
    content.addWidget(formats)

    w.start_recent = QWidget()
    recent = QVBoxLayout(w.start_recent)
    recent.setContentsMargins(0, 8, 0, 0)
    recent.setSpacing(7)
    heading = QLabel("最近项目")
    heading.setObjectName("recentTitle")
    recent.addWidget(heading)
    w.recent_list = QListWidget()
    w.recent_list.setObjectName("recent")
    w.recent_list.setAccessibleName("最近项目")
    w.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.recent_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.recent_list.itemActivated.connect(lambda item: w.open_source(item.data(Qt.ItemDataRole.UserRole)))
    recent.addWidget(w.recent_list)
    content.addWidget(w.start_recent)
    layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch(5)
    return page


def _score_workspace(w):
    surface = QWidget()
    surface.setObjectName("workspace")
    workspace = QVBoxLayout(surface)
    workspace.setContentsMargins(0, 0, 0, 0)
    workspace.setSpacing(0)
    toolbar = QWidget()
    toolbar.setObjectName("editorTools")
    tools = QHBoxLayout(toolbar)
    tools.setContentsMargins(12, 5, 12, 5)
    tools.setSpacing(6)
    w.tabs = QTabBar()
    w.tabs.setExpanding(False)
    w.tabs.setDrawBase(False)
    w.tabs.setAccessibleName("制谱视图")
    w.tabs.addTab("数字简谱")
    w.tabs.addTab("音符编辑")
    tools.addWidget(w.tabs)
    tools.addWidget(_divider(Qt.Orientation.Vertical))
    w.undo_button = _icon_button(tools, "undo", "撤销 · Ctrl+Z", w.undo)
    w.redo_button = _icon_button(tools, "redo", "重做 · Ctrl+Y", w.redo)
    tools.addStretch()
    w.calibration_toggle = _button(tools, "节奏与调号", style="quiet")
    w.calibration_toggle.setAccessibleName("节奏与调号")
    w.calibration_toggle.setCheckable(True)
    w.export_button = _button(tools, "导出", style="export")
    menu = QMenu(w.export_button)
    w.txt_action = menu.addAction("导出 TXT…", lambda: w.export(False))
    w.midi_action = menu.addAction("导出 MIDI…", lambda: w.export(True))
    w.audio_export_action = menu.addAction("导出音频…", w.export_audio)
    w.export_button.setMenu(menu)
    workspace.addWidget(toolbar)
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
    w.key = ComboBox()
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
    workspace.addWidget(calibration)

    w.score_view = ScoreView()
    w.score_scroll = QScrollArea()
    w.score_scroll.setObjectName("scoreScroll")
    w.score_scroll.setAccessibleName("简谱视图")
    w.score_scroll.setWidgetResizable(True)
    w.score_scroll.setWidget(w.score_view)
    w.score_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    pages = QStackedWidget()
    pages.addWidget(w.score_scroll)
    pages.addWidget(_note_editor(w))
    w.tabs.currentChanged.connect(pages.setCurrentIndex)
    workspace.addWidget(pages, 1)
    workspace.addWidget(_player(w))
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
    player.setObjectName("toolbar")
    layout = QVBoxLayout(player)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(_divider(Qt.Orientation.Horizontal))
    transport = QHBoxLayout()
    transport.setContentsMargins(12, 7, 12, 7)
    transport.setSpacing(7)
    w.pause_button = _icon_button(transport, "pause", "暂停播放", w.toggle_pause)
    w.stop_button = _icon_button(transport, "stop", "停止播放", w.stop_playback)

    track_group = QFrame()
    track_group.setObjectName("tracks")
    tracks = QHBoxLayout(track_group)
    tracks.setContentsMargins(3, 3, 3, 3)
    tracks.setSpacing(2)
    w.original_button = _button(tracks, "原曲", w.play_original, style="track", height=26)
    w.vocals_button = _button(tracks, "人声", lambda: w.play_stem(vocals=True), style="track", height=26)
    w.accompaniment_button = _button(tracks, "伴奏", lambda: w.play_stem(vocals=False), style="track", height=26)
    tracks.addWidget(_divider(Qt.Orientation.Vertical))
    w.melody_button = _button(tracks, "旋律", lambda: w.play(original_timing=True), style="track", height=26)
    w.play_button = _button(tracks, "简谱", w.play, style="track", height=26)
    w.track_buttons = (w.original_button, w.vocals_button, w.accompaniment_button, w.melody_button, w.play_button)
    for button in w.track_buttons:
        button.setCheckable(True)
        button.setAccessibleName(f"播放{button.text()}")
        button.setToolTip(button.accessibleName())
    w.melody_button.setToolTip("按识别音符的原始时序试听旋律")
    w.play_button.setToolTip("按简谱节奏播放")
    transport.addWidget(track_group)

    w.timeline = QSlider(Qt.Orientation.Horizontal)
    w.timeline.setMinimumHeight(24)
    w.timeline.setAccessibleName("播放进度")
    w.timeline.sliderReleased.connect(w.seek)
    transport.addWidget(w.timeline, 1)
    w.time_label = QLabel("00:00 / 00:00")
    w.time_label.setObjectName("time")
    transport.addWidget(w.time_label)
    transport.addWidget(_divider(Qt.Orientation.Vertical))
    w.instrument = ComboBox()
    w.instrument.addItems(PROGRAMS)
    _field(transport, "音色", w.instrument)
    w.instrument.currentIndexChanged.connect(w._change_instrument)
    w.rate = ComboBox()
    w.rate.addItems(("0.5×", "0.75×", "1.0×", "1.25×", "1.5×"))
    w.rate.setCurrentIndex(2)
    w.rate.currentIndexChanged.connect(w.change_rate)
    w.rate.setMinimumHeight(32)
    w.rate.setAccessibleName("播放速度")
    w.rate.setToolTip("播放速度")
    transport.addWidget(w.rate)
    transport.addWidget(_divider(Qt.Orientation.Vertical))
    w.volume = QSlider(Qt.Orientation.Horizontal)
    w.volume.setRange(0, 100)
    w.volume.setValue(65)
    w.volume.setFixedWidth(60)
    w.volume.setAccessibleName("播放音量")
    w.volume.setToolTip("播放音量")
    w.volume.valueChanged.connect(lambda value: w._audio.setVolume(value / 100))
    volume_icon = QLabel()
    volume_icon.setPixmap(icon("volume").pixmap(ICON_SIZE, player.devicePixelRatioF()))
    volume_icon.setBuddy(w.volume)
    transport.addWidget(volume_icon)
    transport.addWidget(w.volume)
    layout.addLayout(transport)
    return player


def build_interface(w):
    apply_theme(w)
    central = QWidget()
    w.setCentralWidget(central)
    layout = QVBoxLayout(central)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(_workflow_toolbar(w))
    layout.addWidget(_divider(Qt.Orientation.Horizontal))
    w.pages = QStackedWidget()
    w.start_page = _start_page(w)
    w.editor_page = _score_workspace(w)
    w.pages.addWidget(w.start_page)
    w.pages.addWidget(w.editor_page)
    layout.addWidget(w.pages, 1)

    feedback = QHBoxLayout()
    feedback.setContentsMargins(12, 3, 12, 4)
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
    def switch_editor_tab():
        if w.editor_page.isVisible():
            w.tabs.setCurrentIndex(1 - w.tabs.currentIndex())

    for shortcut in ("Ctrl+Tab", "Ctrl+Shift+Tab"):
        QShortcut(QKeySequence(shortcut), w, switch_editor_tab)
    w.start_import.setFocus()
