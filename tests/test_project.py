import json
from zipfile import ZipFile

import pytest

from noteflow.errors import NoteFlowError
from noteflow.project import load_project


@pytest.mark.parametrize("version", [1, 2])
def test_project_preserves_performance_timing_and_reads_legacy_intent(tmp_path, version):
    import io
    import wave
    data = {
        "version": version, "name": "test", "stems": False, "instrument": "钢琴", "vocal_score": True,
        "notes": [{"id": "a", "start_s": .13, "end_s": .47, "midi": 69, "strength": .32, "velocity": 80}],
        "beat": {"bpm": 100, "first_beat_s": .05, "reliable": True},
        "settings": {"bpm": 100, "first_beat_s": .05, "tonic_pc": 2}, "edited_notes": None,
        "analysis_options": {"target": "vocal", "pitch_min": 48, "pitch_max": 84, "source": "original"},
        "uncertain": [{"start_s": .13, "end_s": .47, "reason": "需要试听"}],
    }
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00" * 44100 * 4)
    path = tmp_path / "project.noteflow"
    with ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps(data))
        archive.writestr("audio/original.wav", audio.getvalue())
    output = tmp_path / "opened"
    output.mkdir()
    project = load_project(path, output)
    assert project.analysis.options.target == "vocal"
    assert [(n.start_s, n.end_s, n.midi) for n in project.score.melody] == [(.13, .47, 69)]
    if version == 2:
        assert project.analysis.options.pitch_min == 48
        assert project.analysis.uncertain[0].reason == "需要试听"


def test_project_rejects_unexpected_paths_without_extracting(tmp_path):
    path = tmp_path / "malicious.noteflow"
    destination = tmp_path / "opened"
    destination.mkdir()
    with ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps({"version": 1, "name": "test", "stems": False}))
        archive.writestr("audio/original.wav", b"invalid")
        archive.writestr("../escaped.txt", b"unexpected")
    with pytest.raises(NoteFlowError, match="项目无法打开"):
        load_project(path, destination)
    assert not (tmp_path / "escaped.txt").exists()
    assert list(destination.iterdir()) == []


def test_failed_save_preserves_existing_project(tmp_path, monkeypatch):
    from noteflow import project
    from noteflow.media import MediaInfo

    path = tmp_path / "existing.noteflow"
    path.write_bytes(b"previous saved project")
    snapshot = project.Project("source.wav", MediaInfo(tmp_path / "source.wav", 0, "pcm_s16le", "wav"),
                               None, None, None)

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(project, "decode_original", fail)
    with pytest.raises(OSError):
        project.save_project(snapshot, path, "ffmpeg")
    assert path.read_bytes() == b"previous saved project"
    assert list(tmp_path.iterdir()) == [path]
