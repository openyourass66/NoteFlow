import os
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from noteflow import desktop, pipeline
from noteflow.analysis import AnalysisResult
from noteflow.desktop_settings import _default_tools
from noteflow.errors import NoteFlowError
from noteflow.media import MediaInfo
from noteflow.notes import NoteEvent
from noteflow.process import check_cancelled
from noteflow.rhythm import BeatEstimate
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
def window(app, tmp_path, monkeypatch):
    import shutil

    tools = replace(_default_tools(), pitch_python="")
    if not shutil.which(tools.ffmpeg) or not shutil.which(tools.ffprobe):
        pytest.skip("Desktop tests require FFmpeg and ffprobe")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = desktop.MainWindow(tmp_path, settings=settings, tools=tools)
    monkeypatch.setattr(window, "_confirm_discard", lambda *args: True)
    window.show()
    yield window
    window.close()
    wait_for(app, lambda: window._thread is None and not window.isVisible())


def test_toolbar_preserves_file_shortcuts_and_recent_projects(app, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    recent = tmp_path / "曲目 & 项目.noteflow"
    settings.setValue("projects/recent", [str(recent)])
    opened = []
    monkeypatch.setattr(desktop.MainWindow, "open_source", lambda self, path: opened.append(Path(path)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(recent), ""))
    window = desktop.MainWindow(tmp_path, settings=settings)
    window.show()
    window.activateWindow()
    app.processEvents()
    try:
        assert window.start_page.isVisible()
        assert not window.editor_page.isVisible()
        QTest.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert opened == [recent]
        action, = window.recent_menu.actions()
        assert action.text() == "曲目 && 项目"
        action.trigger()
        window.recent_list.itemActivated.emit(window.recent_list.item(0))
        assert opened == [recent, recent, recent]
        window._imported(MediaInfo(tmp_path / "音轨.wav", 0, "pcm_s16le", "wav", 2))
        window._sync_controls()
        assert window.editor_page.isVisible()
        assert not window.start_page.isVisible()
        QTest.keyClick(window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        assert window.note_table.isVisible()
    finally:
        window.close()


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

    for action, path in ((window.txt_action, tmp_path / "导出.txt"), (window.midi_action, tmp_path / "导出.mid")):
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), ""))
        assert action.isEnabled()
        action.trigger()
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
        window.play_button.click()
        wait_for(app, lambda: window._thread is None)
        assert window._playing == "演奏", window.status.text()
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
    assert not window.play_button.isEnabled()
    window.original_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window._playing == "原曲", window.status.text()
    assert window.original_button.isChecked()
    wait_for(app, lambda: window._player and window._player.position() >= 150, timeout=10)
    original_path = window._preview_path
    window.pause_button.click()
    assert window._player.playbackState() == desktop.QMediaPlayer.PlaybackState.PausedState
    assert window.pause_button.accessibleName() == "继续播放"
    window.timeline.setValue(1500)
    window.seek()
    assert window._player.position() == 1500
    # Loading another track resumes only once; subsequent seeks stay put.
    window.original_button.click()
    wait_for(app, lambda: window._thread is None and window._player and window._player.position() >= 1500)
    window.pause_button.click()
    assert 1500 <= window._player.position() < 2300
    window.timeline.setValue(2500)
    window.seek()
    assert window._player.position() == 2500
    window.pause_button.click()
    assert window._player.playbackState() == desktop.QMediaPlayer.PlaybackState.PlayingState
    window.stop_button.click()
    wait_for(app, lambda: not original_path.exists(), timeout=2)
    assert window._player is None and source.is_file()
    assert not window.original_button.isChecked()


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

    window.source_mode.setCurrentIndex(window.source_mode.findData("vocal"))
    window.generate_button.click()
    wait_for(app, lambda: window._thread is None)
    assert window.score is not None, window.status.text()
    assert [n.midi for n in window.score.melody] == [midi for _, _, midi in expected]

    from PySide6.QtWidgets import QInputDialog
    import wave

    exported = tmp_path / "exported-vocals.wav"
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **kw: ("人声", True))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(exported), ""))
    window.export_audio()
    wait_for(app, lambda: window._thread is None)
    assert exported.read_bytes() == stems.vocals.read_bytes()
    project = tmp_path / "stems.noteflow"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(project), ""))
    # Real separation writes aligned stereo PCM stems.
    for path in (stems.vocals, stems.accompaniment):
        with wave.open(str(path), "rb") as wav:
            samples = wav.readframes(wav.getnframes())
        import numpy as np
        mono = np.frombuffer(samples, dtype="<i2")
        stereo = np.repeat(mono[:, None], 2, axis=1)
        # Preserve the fixture's 22050 Hz signal while matching the stem format.
        stereo = np.repeat(stereo, 2, axis=0)
        with wave.open(str(path), "wb") as wav:
            wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
            wav.writeframes(stereo.tobytes())
    window.save_project()
    wait_for(app, lambda: window._thread is None)
    window.open_source(project)
    wait_for(app, lambda: window._thread is None)
    assert window.stems is not None and window.stems.vocals.exists(), window.status.text()
    assert window._analysis_vocals and window.source_mode.currentData() == "vocal"
    assert window.pitch_range.count() == 3 and window.pitch_range.currentIndex() == 0
    restored = window.stems
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    assert not window.vocals_button.isEnabled() and not restored.vocals.exists()


@pytest.mark.parametrize("mode", ["instrument", "vocal", "no_demucs", "failed"])
def test_explicit_target_selects_the_input_and_never_falls_back_to_another_voice(app, window, tmp_path, monkeypatch, mode):
    source = tmp_path / "mixed.wav"
    write_wave(source, 3, [(0, 2.5, 40)])
    window.tools = replace(window.tools, demucs_python="" if mode == "no_demucs" else "test-python")
    lead = tuple(NoteEvent(f"v{i}", i * 0.5, i * 0.5 + 0.45, pitch, 0.5, 80)
                 for i, pitch in enumerate((69, 67, 64, 62)))
    beat = BeatEstimate(100, 0.12, True)
    analyzed, separated = [], []

    def analyze(media, *, vocals, find_beats, melody_only, options, **_):
        assert melody_only and find_beats
        analyzed.append(vocals)
        return AnalysisResult(media, 3, lead, beat, candidate_overlap=0.8, options=options)

    def separate(media, destination, **_):
        separated.append(destination)
        if mode == "failed":
            raise NoteFlowError("SEPARATION_FAILED", "separate", "测试分离失败。")
        destination.mkdir()
        stems = Stems(destination / "vocals.wav", destination / "no_vocals.wav")
        stems.vocals.touch()
        stems.accompaniment.touch()
        return stems

    monkeypatch.setattr(pipeline, "analyze_media", analyze)
    monkeypatch.setattr(pipeline, "separate", separate)
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    assert window.source_mode.currentData() == "instrument"
    if mode != "instrument":
        window.source_mode.setCurrentIndex(window.source_mode.findData("vocal"))
    window.generate_button.click()
    wait_for(app, lambda: window._thread is None)
    if mode in {"failed", "no_demucs"}:
        assert window.score is None and analyzed == []
        assert window._stem_workspace is None
    elif mode == "vocal":
        assert analyzed == [window.stems.vocals]
        assert window._analysis_vocals and window.score.melody == lead
        window.generate_button.click()
        wait_for(app, lambda: window._thread is None)
        assert len(separated) == 1
    else:
        assert analyzed == [None] and separated == []
        assert window.score.melody == lead and not window._analysis_vocals


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

    monkeypatch.setattr(pipeline, "analyze_media", slow_analyze)
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


def test_project_restores_edited_notes_and_audio_after_original_is_removed(app, window, tmp_path, monkeypatch):
    source, project = tmp_path / "original.wav", tmp_path / "portable.noteflow"
    write_wave(source, 10, melody())
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    window.generate()
    wait_for(app, lambda: window._thread is None)
    original = window.score.melody
    from PySide6.QtCore import QItemSelectionModel

    window.note_table.selectionModel().select(
        window.note_table.model().index(0, 2),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert window.note_table.currentRow() == -1
    window.transpose_note(12)
    assert window.score.melody[0].midi == original[0].midi + 12
    window.undo()
    assert window.score.melody == original
    window.redo()
    edited = window.score.melody
    assert edited[0].midi == original[0].midi + 12
    window.note_table.item(0, 0).setText("-1")
    assert window.score.melody == edited
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(project), ""))
    window.save_project()
    wait_for(app, lambda: window._thread is None)
    assert project.is_file() and not window._dirty, window.status.text()
    source.unlink()
    window.open_source(project)
    wait_for(app, lambda: window._thread is None)
    assert window.project_path == project and window.media.path.is_file(), window.status.text()
    assert window.score.melody == edited and not window._dirty
    assert len(window.recent_menu.actions()) == 1
    window.bpm.setValue(100)
    window.apply_calibration()
    wait_for(app, lambda: window._thread is None)
    assert window.score.melody == edited
    assert window.score.settings.bpm == 100


def test_broken_project_preserves_current_work(app, window, tmp_path):
    source = tmp_path / "existing.wav"
    write_wave(source, 1, [(0, .5, 60)])
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    previous = window.media
    broken = tmp_path / "broken.noteflow"
    broken.write_bytes(b"broken")
    window.open_source(broken)
    wait_for(app, lambda: window._thread is None)
    assert window.media is previous and window._loading_workspace is None


def test_save_then_close_waits_for_project_write(app, window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    source, project = tmp_path / "save.wav", tmp_path / "saved.noteflow"
    write_wave(source, 1, [(0, .5, 60)])
    window.open_source(source)
    wait_for(app, lambda: window._thread is None)
    window._mark_dirty()
    monkeypatch.setattr(window, "_confirm_discard", desktop.MainWindow._confirm_discard.__get__(window))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel)
    window.close()
    assert window.isVisible() and window.media
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(project), ""))
    window.close()
    wait_for(app, lambda: window._thread is None and not window.isVisible())
    assert project.is_file()
