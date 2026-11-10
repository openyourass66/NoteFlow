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
    demucs_python: str = ""


def _tool_directories() -> tuple[Path, ...]:
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).resolve().parent
        workspace = next((parent for parent in directory.parents
                          if (parent / "packaging" / "noteflow.spec").is_file()), None)
        return (directory / "tools", workspace / ".tools") if workspace else (directory / "tools",)
    return (Path(__file__).resolve().parents[2] / ".tools",)


def _default_tools() -> Tools:
    directories = _tool_directories()

    def find(*patterns: str) -> str:
        for directory in directories:
            for pattern in patterns:
                for path in sorted(directory.glob(pattern)):
                    if path.is_file():
                        return str(path)
        return ""

    return Tools(
        find("ffmpeg.exe", "ffmpeg/bin/ffmpeg.exe", "ffmpeg/*/bin/ffmpeg.exe") or "ffmpeg",
        find("ffprobe.exe", "ffmpeg/bin/ffprobe.exe", "ffmpeg/*/bin/ffprobe.exe") or "ffprobe",
        find("fluidsynth.exe", "fluidsynth/bin/fluidsynth.exe", "fluidsynth/*/bin/fluidsynth.exe") or "fluidsynth",
        find("*.sf2"),
        find("demucs/Scripts/python.exe"),
    )


def load_tools(settings: QSettings) -> Tools:
    defaults = _default_tools()
    values = {}
    for name in ("ffmpeg", "ffprobe", "fluidsynth", "soundfont", "demucs_python"):
        fallback = getattr(defaults, name)
        configured = settings.value(f"tools/{name}", fallback, str)
        if name in ("ffmpeg", "ffprobe", "fluidsynth", "demucs_python") and configured.lower() in ("", name, f"{name}.exe"):
            configured = fallback
        values[name] = os.environ.get(f"NOTEFLOW_{name.upper()}") or configured
    return Tools(**values)


def edit_tools(parent: QWidget, settings: QSettings, tools: Tools) -> Tools:
    dialog = QDialog(parent)
    dialog.setWindowTitle("工具与音源")
    dialog.resize(650, 280)
    outer = QVBoxLayout(dialog)
    form = QFormLayout()
    outer.addLayout(form)
    edits = {}
    for name, label in (("ffmpeg", "FFmpeg"), ("ffprobe", "ffprobe"),
                        ("fluidsynth", "FluidSynth"), ("soundfont", "SoundFont（SF2）"),
                        ("demucs_python", "Demucs Python")):
        edit = QLineEdit(getattr(tools, name))
        edit.setMinimumHeight(36)
        edit.setAccessibleName(label)
        placeholder = {"soundfont": "选择本地 SF2 文件", "demucs_python": "选择已安装 Demucs 的 python.exe"}
        edit.setPlaceholderText(placeholder.get(name, "输入路径或从 PATH 查找"))
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
