import json
from zipfile import ZipFile

import pytest

from noteflow.errors import NoteFlowError
from noteflow.project import load_project


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
