import os
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
        final_path = window._preview_path
        window.stop_button.click()
        assert window._player is None
        wait_for(app, lambda: not final_path.exists(), timeout=2)


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
