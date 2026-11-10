"""Local tool paths shared by the desktop window and its background jobs."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)


@dataclass(frozen=True, slots=True)
class Tools:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    fluidsynth: str = "fluidsynth"
    soundfont: str = ""


def _default_tools():
    defaults = Tools()
    if getattr(sys, "frozen", False):
        return defaults
    root = Path(__file__).resolve().parents[2] / ".tools"
    ffmpeg = next(iter(sorted(root.glob("ffmpeg/*/bin/ffmpeg.exe"))), None)
    ffprobe = next(iter(sorted(root.glob("ffmpeg/*/bin/ffprobe.exe"))), None)
    synth = next(iter(sorted(root.glob("fluidsynth/*/bin/fluidsynth.exe"))), None)
    soundfont = next(iter(sorted(root.glob("*.sf2"))), None)
    return Tools(str(ffmpeg or defaults.ffmpeg), str(ffprobe or defaults.ffprobe),
                 str(synth or defaults.fluidsynth), str(soundfont) if soundfont else "")


def load_tools(settings: QSettings) -> Tools:
    defaults = _default_tools()
    return Tools(**{
        name: os.environ.get(f"NOTEFLOW_{name.upper()}") or settings.value(f"tools/{name}", getattr(defaults, name), str)
        for name in ("ffmpeg", "ffprobe", "fluidsynth", "soundfont")
    })


def edit_tools(parent: QWidget, settings: QSettings, tools: Tools) -> Tools:
    dialog = QDialog(parent)
    dialog.setWindowTitle("工具与音源")
    dialog.resize(650, 240)
    outer = QVBoxLayout(dialog)
    form = QFormLayout()
    outer.addLayout(form)
    edits = {}
    for name, label in (("ffmpeg", "FFmpeg"), ("ffprobe", "ffprobe"),
                        ("fluidsynth", "FluidSynth"), ("soundfont", "SoundFont（SF2）")):
        edit = QLineEdit(getattr(tools, name))
        edit.setMinimumHeight(36)
        edit.setAccessibleName(label)
        edit.setPlaceholderText("选择本地 SF2 文件" if name == "soundfont" else "输入路径或从 PATH 查找")
        edits[name] = edit
        browse = QPushButton("浏览…")
        browse.setAccessibleName(f"浏览 {label}")
        browse.setMinimumHeight(36)

        def choose(_checked=False, field=edit, soundfont=(name == "soundfont")):
            file_type = "SoundFont (*.sf2)" if soundfont else "可执行文件 (*.exe)"
            selected, _ = QFileDialog.getOpenFileName(dialog, "选择文件", field.text(), file_type)
            if selected:
                field.setText(selected)

        browse.clicked.connect(choose)
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form.addRow(label, row)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    outer.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return tools
    result = {name: edit.text().strip() for name, edit in edits.items()}
    for name in ("ffmpeg", "ffprobe", "fluidsynth"):
        result[name] = result[name] or name
    for name, value in result.items():
        settings.setValue(f"tools/{name}", value)
    return Tools(**result)
