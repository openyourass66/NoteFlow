"""Native controls for explicit, bounded cloud audio review."""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .desktop_theme import ComboBox
from .review import ReviewLimits
from .review_cloud import CloudConfig, DEFAULT_MODEL
from .review_settings import load_connection, save_connection


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    config: CloudConfig
    limits: ReviewLimits
    start_s: float
    end_s: float
    calibration: bool = False


class ReviewDialog(QDialog):
    def __init__(self, parent, settings, duration=None):
        super().__init__(parent)
        self.settings, self.request = settings, None
        self.duration = duration
        is_review = duration is not None
        self.setWindowTitle("音频复核 · 实验功能" if is_review else "云端模型设置")
        self.setMinimumWidth(610)
        layout = QVBoxLayout(self)
        intro = QLabel("对照原曲和钢琴演奏，复核音高、节奏与连贯性。"
                       if is_review else "填写支持 WAV 音频输入的 Chat Completions 接口。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        layout.addLayout(form)
        config, message = load_connection(settings)
        self.url = QLineEdit(config.base_url)
        self.url.setPlaceholderText("https://api.example.com/v1")
        self.model = ComboBox()
        self.model.setEditable(True)
        self.model.addItems([DEFAULT_MODEL, "qwen3.5-omni-plus", "qwen3.5-omni-flash", "qwen3-omni-flash"])
        self.model.setCurrentText(config.model)
        self.protocol = ComboBox()
        for label, protocol in (("自动（按服务地址）", "auto"), ("OpenAI 兼容（Base64）", "openai"),
                                ("百炼兼容（Data URI）", "dashscope")):
            self.protocol.addItem(label, protocol)
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(config.protocol)))
        self.key = QLineEdit(config.api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("填写服务商提供的 API Key")
        self._restored_key_url = config.base_url if config.api_key else ""
        self.url.textChanged.connect(self._endpoint_changed)
        self.key.textEdited.connect(self._key_edited)
        for label, control in (("Base URL", self.url), ("音频模型", self.model),
                               ("接口格式", self.protocol), ("API Key", self.key)):
            control.setMinimumHeight(36)
            control.setAccessibleName(label)
            form.addRow(label, control)
        hint = QLabel("配置保存在本机，API Key 由当前 Windows 用户加密。清空 Key 后保存可移除凭据。")
        hint.setWordWrap(True)
        form.addRow(hint)

        if is_review:
            self._add_review_options(form, duration)
            notice = QLabel("开始后，所选范围的原曲与演奏片段将发送到填写的服务地址，按服务商规则计费。\n"
                            "每 20 秒分段，对照请求也计入次数。能力检查上传内置旋律，最多请求 6 次。")
            notice.setWordWrap(True)
            layout.addWidget(notice)
        self.error = QLabel(message)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setAccessibleName("配置提示")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        cancel.setMinimumHeight(36)
        buttons.rejected.connect(self.reject)
        save = buttons.addButton("仅保存配置" if is_review else "保存", QDialogButtonBox.ButtonRole.ActionRole)
        save.clicked.connect(self.save)
        if not is_review:
            save.setObjectName("primary")
        if is_review:
            self.start_button = buttons.addButton("上传并开始复核", QDialogButtonBox.ButtonRole.AcceptRole)
            self.start_button.setObjectName("primary")
            self.start_button.setMinimumHeight(36)
            calibration = buttons.addButton("检查复核能力（6 次）", QDialogButtonBox.ButtonRole.ActionRole)
            calibration.setMinimumHeight(36)
            calibration.setToolTip("上传内置的已知旋律及错音、错八度和断奏样本，最多请求 6 次")
            calibration.clicked.connect(lambda: self.submit(calibration=True))
            # Uploads require activating their named button rather than pressing Enter in a field.
            self.start_button.setAutoDefault(False)
            buttons.accepted.connect(self.submit)
        save.setDefault(True)
        save.setMinimumHeight(36)
        layout.addWidget(buttons)

    def _endpoint_changed(self, text):
        if self._restored_key_url and text.strip().rstrip("/") != self._restored_key_url:
            self.key.clear()
            self._restored_key_url = ""
            self.error.setText("服务地址已修改，请填写新地址对应的 API Key。")

    def _key_edited(self):
        self._restored_key_url = ""

    def _add_review_options(self, form, duration):
        interval = QHBoxLayout()
        self.start, self.end = QDoubleSpinBox(), QDoubleSpinBox()
        for label, control in (("复核开始秒数", self.start), ("复核结束秒数", self.end)):
            control.setDecimals(3)
            control.setRange(0, duration)
            control.setSuffix(" 秒")
            control.setMinimumHeight(36)
            control.setAccessibleName(label)
        self.end.setValue(min(duration, 20))
        interval.addWidget(self.start)
        interval.addWidget(QLabel("至"))
        interval.addWidget(self.end)
        full = QPushButton("整段")
        full.setMinimumHeight(36)
        full.clicked.connect(lambda: (self.start.setValue(0), self.end.setValue(duration)))
        interval.addWidget(full)
        form.addRow("复核范围", interval)
        self.rounds, self.calls = QSpinBox(), QSpinBox()
        self.rounds.setRange(1, 3)
        self.rounds.setValue(3)
        self.calls.setRange(1, 60)
        self.calls.setValue(24)
        for label, control in (("最多轮数", self.rounds), ("最多请求次数", self.calls)):
            control.setMinimumHeight(36)
            control.setAccessibleName(label)
            form.addRow(label, control)

    def _connection(self):
        return CloudConfig(self.url.text().strip().rstrip("/"), self.model.currentText().strip(),
                           self.key.text().strip(), self.protocol.currentData())

    def save(self):
        try:
            config = self._connection()
            config.validate(require_key=False)
            save_connection(self.settings, config)
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()

    def submit(self, *, calibration=False):
        try:
            config = self._connection()
            config.validate()
            if not calibration and self.end.value() - self.start.value() < .1:
                raise ValueError("请选择至少 0.1 秒的有效范围。")
            save_connection(self.settings, config)
            self.request = ReviewRequest(config, ReviewLimits(self.rounds.value(), self.calls.value()),
                                         self.start.value(), min(self.end.value(), self.duration), calibration)
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()


def show_calibration(parent, report):
    dialog = QDialog(parent)
    dialog.setWindowTitle("复核能力检查")
    dialog.resize(660, 460)
    layout = QVBoxLayout(dialog)
    labels = {"passed": "6项受控检查通过，仍需用真实素材试听验证。", "failed": "受控检查未全部通过，暂不建议依赖此模型自动修正。",
              "cancelled": "检查已取消。", "error": "检查中断。", "prepared": "测试音频已准备，尚未调用云端。"}
    label = QLabel(labels[report["status"]] + f" 已请求 {report['calls']} 次。\n这不是实际歌曲的音准准确率。")
    label.setWordWrap(True)
    layout.addWidget(label)
    names = {"clean": "正确旋律（允许音色不同）", "pitch": "错音高", "octave": "错八度", "fragmented": "断奏",
             "order_normal": "前后对照", "order_reversed": "交换播放顺序后的对照"}
    details = []
    for check in report["checks"]:
        details.append(f"{names[check['case']]}：{'通过' if check['ok'] else '未通过'}")
        details.append(check["response"]["summary"])
        for issue in check["response"].get("issues", []):
            details.append(f"  {issue['start_s']:.2f}–{issue['end_s']:.2f} 秒：{issue['explanation']}")
        details.append("")
    if report.get("error"):
        details.append(report["error"])
    view = QPlainTextEdit("\n".join(details))
    view.setReadOnly(True)
    view.setAccessibleName("受控听辨检查结果")
    layout.addWidget(view)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
