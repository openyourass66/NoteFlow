from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from noteflow import desktop_settings


def test_packaged_app_finds_project_tools_even_with_saved_command_names(tmp_path, monkeypatch):
    workspace = tmp_path / "中文 项目"
    spec = workspace / "packaging" / "noteflow.spec"
    spec.parent.mkdir(parents=True)
    spec.touch()
    executable = workspace / "dist" / "NoteFlow" / "NoteFlow.exe"
    monkeypatch.setattr(desktop_settings, "sys", SimpleNamespace(executable=str(executable), frozen=True))
    tool_dir = workspace / ".tools" / "ffmpeg" / "ffmpeg-test" / "bin"
    tool_dir.mkdir(parents=True)
    for tool in ("ffmpeg", "ffprobe"):
        (tool_dir / f"{tool}.exe").touch()
        monkeypatch.delenv(f"NOTEFLOW_{tool.upper()}", raising=False)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("tools/ffprobe", "ffprobe.exe")

    tools = desktop_settings.load_tools(settings)
    assert tools.ffprobe == str(tool_dir / "ffprobe.exe")
    assert tools.ffmpeg == str(tool_dir / "ffmpeg.exe")


def test_portable_app_uses_adjacent_tools_and_honors_explicit_overrides(tmp_path, monkeypatch):
    executable = tmp_path / "portable" / "NoteFlow.exe"
    monkeypatch.setattr(desktop_settings, "sys", SimpleNamespace(executable=str(executable), frozen=True))
    tool_dir = executable.parent / "tools"
    tool_dir.mkdir(parents=True)
    for name in ("ffprobe.exe", "ffmpeg.exe", "bank.sf2"):
        (tool_dir / name).touch()
    monkeypatch.delenv("NOTEFLOW_FFPROBE", raising=False)
    monkeypatch.delenv("NOTEFLOW_SOUNDFONT", raising=False)
    ffmpeg = str(tmp_path / "other-ffmpeg.exe")
    monkeypatch.setenv("NOTEFLOW_FFMPEG", ffmpeg)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("tools/ffmpeg", str(tool_dir / "ffmpeg.exe"))

    tools = desktop_settings.load_tools(settings)
    assert tools.ffmpeg == ffmpeg
    assert tools.ffprobe == str(tool_dir / "ffprobe.exe")
    assert tools.soundfont == str(tool_dir / "bank.sf2")

    custom_probe = str(tmp_path / "custom" / "ffprobe.exe")
    settings.setValue("tools/ffprobe", custom_probe)
    assert desktop_settings.load_tools(settings).ffprobe == custom_probe
