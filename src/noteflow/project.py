"""Portable, versioned projects with bounded audio and atomic saves."""

import json
import math
import os
import shutil
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Event
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED

from .analysis import AnalysisResult
from .errors import NoteFlowError
from .export import PROGRAMS
from .media import MAX_SECONDS, MediaInfo, decode_original
from .notes import NoteEvent
from .options import AnalysisOptions, UncertainRegion
from .process import check_cancelled
from .rhythm import BeatEstimate
from .score import Score, ScoreSettings, build_score
from .separation import Stems


@dataclass(frozen=True)
class Project:
    name: str
    media: MediaInfo
    analysis: AnalysisResult | None
    score: Score | None
    stems: Stems | None
    edited_notes: tuple[NoteEvent, ...] | None = None
    instrument: str = "钢琴"
    vocal_score: bool = False


def save_project(project: Project, path: Path, ffmpeg: str, cancel: Event | None = None) -> None:
    with NamedTemporaryFile(dir=path.parent, prefix=".noteflow-", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with TemporaryDirectory(prefix="save-") as folder:
            original = decode_original(project.media, Path(folder) / "original.wav", ffmpeg, cancel)
            data = {
                "version": 2, "name": project.name, "instrument": project.instrument,
                "notes": [asdict(n) for n in project.analysis.notes] if project.analysis else None,
                "beat": asdict(project.analysis.beat) if project.analysis else None,
                "settings": asdict(project.score.settings) if project.score else None,
                "edited_notes": [asdict(n) for n in project.edited_notes] if project.edited_notes is not None else None,
                "stems": project.stems is not None,
                "vocal_score": project.vocal_score,
                "analysis_options": asdict(project.analysis.options) if project.analysis else None,
                "uncertain": [asdict(r) for r in project.analysis.uncertain] if project.analysis else [],
            }
            with ZipFile(temporary, "w") as archive:
                archive.writestr("project.json", json.dumps(data, ensure_ascii=False), compress_type=ZIP_DEFLATED)
                archive.write(original, "audio/original.wav", compress_type=ZIP_STORED)
                if project.stems:
                    for name, source in (("vocals", project.stems.vocals), ("accompaniment", project.stems.accompaniment)):
                        check_cancelled(cancel)
                        archive.write(source, f"audio/{name}.wav", compress_type=ZIP_STORED)
            check_cancelled(cancel)
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _notes(items, duration):
    if not isinstance(items, list) or len(items) > 100000:
        raise ValueError("Invalid note list")
    result = []
    ids = set()
    for item in items:
        note = NoteEvent(**item)
        if (not isinstance(note.id, str) or not note.id or note.id in ids
                or not all(math.isfinite(x) for x in (note.start_s, note.end_s))
                or not 0 <= note.start_s < note.end_s <= duration + 0.001
                or type(note.midi) is not int or not 0 <= note.midi <= 127
                or type(note.velocity) is not int or not 1 <= note.velocity <= 127
                or (note.strength is not None and not 0 <= note.strength <= 1)):
            raise ValueError("Invalid note")
        ids.add(note.id)
        result.append(note)
    return tuple(sorted(result, key=lambda n: n.start_s))


def load_project(path: Path, directory: Path, cancel: Event | None = None) -> Project:
    """Extract only known members into a fresh directory owned by the caller."""
    try:
        with ZipFile(path) as archive:
            members = archive.infolist()
            if (len(members) > 4 or len({m.filename for m in members}) != len(members)
                    or sum(m.file_size for m in members) > 100_000_000
                    or archive.getinfo("project.json").file_size > 8_000_000):
                raise ValueError("Project exceeds limits")
            data = json.loads(archive.read("project.json"))
            if data["version"] not in (1, 2) or not isinstance(data["name"], str) or len(data["name"]) > 1024:
                raise ValueError("Unsupported project")
            expected = {"project.json", "audio/original.wav"}
            if data["stems"] is True:
                expected.update(("audio/vocals.wav", "audio/accompaniment.wav"))
            if {m.filename for m in members} != expected:
                raise ValueError("Unexpected project members")
            durations = {}
            for name in sorted(expected - {"project.json"}):
                check_cancelled(cancel)
                target = directory / Path(name).name
                with archive.open(name) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                with wave.open(str(target), "rb") as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    if (not 0 < duration <= MAX_SECONDS or wav.getnchannels() != 2
                            or wav.getsampwidth() != 2 or wav.getframerate() not in (44100, 48000)
                            or len(wav.readframes(wav.getnframes())) != wav.getnframes() * 4):
                        raise ValueError("Invalid project audio")
                durations[name] = duration
            duration = durations["audio/original.wav"]
            if any(abs(value - duration) > 0.01 for value in durations.values()):
                raise ValueError("Misaligned stems")
            media = MediaInfo(directory / "original.wav", 0, "pcm_s16le", "wav", duration)
            analysis = score = edited = None
            if data["notes"] is not None:
                beat = BeatEstimate(**data["beat"])
                ScoreSettings(beat.bpm, beat.first_beat_s)
                options = (AnalysisOptions(**data["analysis_options"]) if data["version"] == 2
                           else AnalysisOptions(target="vocal" if data.get("vocal_score") else "instrument"))
                uncertain = tuple(UncertainRegion(**r) for r in data.get("uncertain", []))
                if any(not 0 <= r.start_s < r.end_s <= duration + 0.001
                       or not isinstance(r.reason, str) or len(r.reason) > 256 for r in uncertain):
                    raise ValueError("Invalid uncertainty metadata")
                analysis = AnalysisResult(media, duration, _notes(data["notes"], duration), beat,
                                          options=options, uncertain=uncertain)
                if data["edited_notes"] is not None:
                    edited = _notes(data["edited_notes"], duration)
                score = build_score(analysis.notes if edited is None else edited, ScoreSettings(**data["settings"]))
            elif data["settings"] is not None or data["edited_notes"] is not None:
                raise ValueError("Score without analysis")
            instrument = data["instrument"]
            if instrument not in PROGRAMS:
                raise ValueError("Unknown instrument")
            stems = Stems(directory / "vocals.wav", directory / "accompaniment.wav") if data["stems"] else None
            check_cancelled(cancel)
            return Project(data["name"], media, analysis, score, stems, edited, instrument,
                           data.get("vocal_score", False) is True)
    except (OSError, BadZipFile, KeyError, ValueError, TypeError, AttributeError, EOFError, wave.Error, RuntimeError) as exc:
        raise NoteFlowError("PROJECT_INVALID", "project", "项目无法打开，文件可能损坏、版本不兼容或超过容量限制。") from exc
