"""Native controls for explicit, bounded cloud audio review."""

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .review import ReviewLimits
from .review_qwen import DEFAULT_MODEL, QwenConfig


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    config: QwenConfig
    limits: ReviewLimits
    start_s: float
    end_s: float
    calibration: bool = False


class ReviewDialog(QDialog):
    def __init__(self, parent, settings, duration, api_key=""):
        super().__init__(parent)
        self.settings, self.request = settings, None
        self.duration = duration
        self.setWindowTitle("音频复核 · 实验功能")
        self.setMinimumWidth(610)
        layout = QVBoxLayout(self)
        intro = QLabel("对照原曲和钢琴演奏，复核音高、节奏与连贯性。\n只采用有本地证据且前后对照一致支持的修改；可随时取消并撤销修改。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        layout.addLayout(form)
        self.url = QLineEdit(os.environ.get("NOTEFLOW_REVIEW_BASE_URL") or settings.value("review/base_url", "", str))
        self.url.setPlaceholderText("https://业务空间ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems([DEFAULT_MODEL, "qwen3.5-omni-plus", "qwen3.5-omni-flash", "qwen3-omni-flash"])
        self.model.setCurrentText(os.environ.get("NOTEFLOW_REVIEW_MODEL") or settings.value("review/model", DEFAULT_MODEL, str))
        self.key = QLineEdit(api_key or os.environ.get("DASHSCOPE_API_KEY", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("仅本次打开软件期间保留，不写入项目或设置文件")
        for label, control in (("百炼 Base URL", self.url), ("音频模型", self.model), ("API Key", self.key)):
            control.setMinimumHeight(36)
            control.setAccessibleName(label)
            form.addRow(label, control)
        hint = QLabel('在 <a style="color:#b7c4ff" href="https://bailian.console.aliyun.com/">百炼控制台</a> 复制 Base URL 与同地域的 Key。'
                      ' <a style="color:#b7c4ff" href="https://help.aliyun.com/zh/model-studio/qwen-omni">接口说明</a>')
        hint.setOpenExternalLinks(True)
        hint.setWordWrap(True)
        form.addRow(hint)
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
        notice = QLabel("开始后，所选范围的原曲与演奏片段将发送到上述阿里云接口，按服务商规则计费。\n"
                        "长片段每 20 秒分段；交换顺序的对照也计入请求次数。请求上限不是金额上限。\n"
                        "“检查复核能力”仅上传内置测试旋律，固定最多 6 次请求，不修改当前乐谱。\n"
                        "“复核通过”仅表示模型未发现明显问题，不代表准确率。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setAccessibleName("配置提示")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.start_button = buttons.addButton("上传并开始复核", QDialogButtonBox.ButtonRole.AcceptRole)
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumHeight(36)
        calibration = buttons.addButton("检查复核能力（6 次）", QDialogButtonBox.ButtonRole.ActionRole)
        calibration.setMinimumHeight(36)
        calibration.setToolTip("仅上传内置的已知旋律及错音、错八度、断奏样本，进行6次请求；不上传当前原曲")
        calibration.clicked.connect(lambda: self.submit(calibration=True))
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def submit(self, *, calibration=False):
        try:
            config = QwenConfig(self.url.text().strip().rstrip("/"), self.model.currentText().strip(), self.key.text().strip())
            config.validate()
            if not calibration and self.end.value() - self.start.value() < .1:
                raise ValueError("请选择至少 0.1 秒的有效范围。")
            self.request = ReviewRequest(config, ReviewLimits(self.rounds.value(), self.calls.value()),
                                         self.start.value(), min(self.end.value(), self.duration), calibration)
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.settings.setValue("review/base_url", config.base_url)
        self.settings.setValue("review/model", config.model)
        self.accept()


def show_report(parent, result, report_path, current_notes=None):
    from .review_results_ui import ReviewReportDialog
    dialog = ReviewReportDialog(parent, result, report_path, current_notes if current_notes is not None else result.notes)
    dialog.exec()
    action = dialog.action
    dialog.deleteLater()
    return action


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
