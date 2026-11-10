"""Run the local transcription pipeline and own its temporary files."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .media import MediaInfo, normalize, probe
from .transcription import NoteEvent, transcribe


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    media: MediaInfo
    duration_s: float
    notes: tuple[NoteEvent, ...]


def analyze(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> AnalysisResult:
    media = probe(path, ffprobe)
    with TemporaryDirectory(prefix="noteflow-") as directory:
        audio = normalize(media, Path(directory), ffmpeg)
        return AnalysisResult(media, audio.duration_s, transcribe(audio))
