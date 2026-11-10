"""Run the local transcription pipeline and own its temporary files."""

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from .media import MediaInfo, normalize, probe
from .notes import NoteEvent
from .process import check_cancelled
from .rhythm import BeatEstimate, estimate
from .transcription import transcribe


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    media: MediaInfo
    duration_s: float
    notes: tuple[NoteEvent, ...]
    beat: BeatEstimate = BeatEstimate()


def analyze(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> AnalysisResult:
    return analyze_media(probe(path, ffprobe), ffmpeg=ffmpeg)


def analyze_media(
    media: MediaInfo, *, ffmpeg: str = "ffmpeg", find_beats: bool = False,
    workdir: Path | None = None, cancel: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> AnalysisResult:
    with TemporaryDirectory(prefix="noteflow-", dir=workdir) as directory:
        if progress:
            progress("正在解码音轨…")
        audio = normalize(media, Path(directory), ffmpeg, cancel=cancel)
        check_cancelled(cancel)
        if progress:
            progress("正在识别音高…")
        notes = transcribe(audio)
        check_cancelled(cancel)
        if progress and find_beats:
            progress("正在估计节奏…")
        beat = estimate(audio) if find_beats else BeatEstimate()
        check_cancelled(cancel)
        return AnalysisResult(media, audio.duration_s, notes, beat)
