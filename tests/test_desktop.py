import os
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import QApplication, QFileDialog

from noteflow import desktop
from noteflow.desktop_settings import _default_tools
from noteflow.process import check_cancelled
from noteflow.score import to_text
from noteflow.separation import Stems
from poc.fixtures import melody, write_wave


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_for(app, condition, timeout=100):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        sleep(0.01)
    pytest.fail("Desktop operation timed out")


@pytest.fixture
def window(app, tmp_path):
    import shutil

    tools = _default_tools()
    if not shutil.which(tools.ffmpeg) or not shutil.which(tools.ffprobe):
        pytest.skip("Desktop tests require FFmpeg and ffprobe")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = desktop.MainWindow(tmp_path, settings=settings, tools=tools)
    window.show()
    yield window
    window.close()
    wait_for(app, lambda: window._thread is None and not window.isVisible())


def test_desktop_generates_calibrates_and_exports(app, window, tmp_path, monkeypatch):
    source = tmp_path / "旋律 样本.wav"
    write_wave(source, 10, melody())
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    assert window.generate_button.isEnabled()
    window.generate_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window.score is not None, window.status.text()
    assert len(window.score.grid.notes) == 12
    assert window.score_view.score is window.score

    analysis, previous = window.analysis, window.score
    window.bpm.setValue(120)
    window.offset.setValue(0)
    window.key.setCurrentIndex(2)
    window.apply_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window.analysis is analysis
    assert window.score.revision > previous.revision
    assert window.score.settings.tonic_pc == 2

    import mido

    for button, path in ((window.txt_button, tmp_path / "导出.txt"), (window.midi_button, tmp_path / "导出.mid")):
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), ""))
        button.click()
        assert path.is_file(), window.status.text()
    assert (tmp_path / "导出.txt").read_text(encoding="utf-8") == to_text(window.score)
    assert mido.MidiFile(tmp_path / "导出.mid").tracks[0][2].key == "D"

    import shutil

    if QMediaDevices.audioOutputs() and shutil.which(window.tools.fluidsynth) and Path(window.tools.soundfont).is_file():
        window.play_button.click()
        wait_for(app, lambda: window._thread is None)
        assert window._player is not None, window.status.text()
        wait_for(app, lambda: window._player and window._player.position() >= 150, timeout=10)
        for index in (1, 2):
            previous_path = window._preview_path
            window.instrument.setCurrentIndex(index)
            wait_for(app, lambda: window._thread is None)
            assert window._player is not None, window.status.text()
            wait_for(app, lambda: window._player and window._player.position() >= 150, timeout=10)
            assert not previous_path.exists()
        window.melody_button.click()
        wait_for(app, lambda: window._thread is None)
        assert window._playing == "旋律", window.status.text()
        wait_for(app, lambda: window._player and window._player.position() >= 150, timeout=10)
        final_path = window._preview_path
        window.stop_button.click()
        assert window._player is None
        wait_for(app, lambda: not final_path.exists(), timeout=2)


def test_original_is_available_before_generation_without_soundfont(app, window, tmp_path):
    if not QMediaDevices.audioOutputs():
        pytest.skip("Original playback requires an audio device")
    window.tools = replace(window.tools, soundfont="")
    source = tmp_path / "试听 原曲.wav"
    write_wave(source, 10, melody())
    assert not window.original_button.isEnabled()
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    assert window.original_button.isEnabled()
    assert not window.melody_button.isEnabled()
    assert not window.play_button.isEnabled()
    window.original_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window._playing == "原曲", window.status.text()
    wait_for(app, lambda: window._player and window._player.position() >= 150, timeout=10)
    original_path = window._preview_path
    window.stop_button.click()
    wait_for(app, lambda: not original_path.exists(), timeout=2)
    assert window._player is None and source.is_file()


def test_desktop_can_preview_stems_and_transcribe_only_vocals(app, window, tmp_path, monkeypatch):
    source = tmp_path / "mixed.wav"
    expected = melody()
    write_wave(source, 10, [(0, 9, 43)])
    window.tools = replace(window.tools, demucs_python="test-python")

    def separate(media, destination, **_):
        assert media.path == source
        destination.mkdir()
        vocals, accompaniment = destination / "vocals.wav", destination / "no_vocals.wav"
        write_wave(vocals, 10, expected)
        write_wave(accompaniment, 10, [(0, 9, 43)])
        return Stems(vocals, accompaniment)

    monkeypatch.setattr(desktop, "separate", separate)
    played = []
    monkeypatch.setattr(window, "_play_rendered", lambda path, label: played.append((path, label)))
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    assert not window.vocals_button.isEnabled()
    window.separate_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window.stems is not None, window.status.text()
    stems = window.stems
    window.vocals_button.click()
    window.accompaniment_button.click()
    assert played == [(stems.vocals, "人声"), (stems.accompaniment, "伴奏")]

    window.generate_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window.score is not None, window.status.text()
    assert [n.midi for n in window.score.melody] == [midi for _, _, midi in expected]

    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    assert not window.vocals_button.isEnabled() and not stems.vocals.exists()


def test_desktop_cancellation_and_source_changes_discard_late_results(app, window, tmp_path, monkeypatch):
    sources = [tmp_path / f"source-{index}.wav" for index in range(3)]
    for source in sources:
        write_wave(source, 1)
    entered = []

    def slow_analyze(*_args, cancel, **_kwargs):
        entered.append(True)
        cancel.wait(timeout=10)
        check_cancelled(cancel)
        pytest.fail("Expected the task to be cancelled")

    monkeypatch.setattr(desktop, "analyze_media", slow_analyze)
    window.open_source(sources[0])
    wait_for(app, lambda: window._thread is None)
    window.generate_button.click()
    wait_for(app, lambda: len(entered) == 1)
    window.cancel_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window.score is None and window.generate_button.isEnabled()

    window.generate_button.click()
    wait_for(app, lambda: len(entered) == 2)
    window.open_source(sources[1])
    window.open_source(sources[2])
    wait_for(app, lambda: window._thread is None)
    assert window.score is None and window.media.path == sources[2].resolve()

    window.generate_button.click()
    wait_for(app, lambda: len(entered) == 3)
    workspace = window.workdir
    window.close()
    wait_for(app, lambda: window._thread is None and not window.isVisible())
    assert not workspace.exists()
