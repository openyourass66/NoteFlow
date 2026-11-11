"""Run the local transcription pipeline and own its temporary files."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from .media import MediaInfo, normalize, probe
from .notes import NoteEvent
from .process import check_cancelled
from .rhythm import BeatEstimate, estimate
from .separation import separate
from .transcription import refine_octaves, transcribe, transcribe_melody


HEAVY_OVERLAP = 0.3


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    media: MediaInfo
    duration_s: float
    notes: tuple[NoteEvent, ...]
    beat: BeatEstimate = BeatEstimate()
    candidate_overlap: float | None = None


def analyze(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
            demucs_python: str | None = None) -> AnalysisResult:
    media = probe(path, ffprobe)
    if demucs_python is None:
        return analyze_media(media, ffmpeg=ffmpeg)
    with TemporaryDirectory(prefix="noteflow-stems-") as directory:
        stems = separate(media, Path(directory) / "stems", python=demucs_python, ffmpeg=ffmpeg)
        return analyze_media(media, ffmpeg=ffmpeg, vocals=stems.vocals)


def analyze_media(
    media: MediaInfo, *, ffmpeg: str = "ffmpeg", find_beats: bool = False,
    workdir: Path | None = None, cancel: Event | None = None,
    progress: Callable[[str], None] | None = None, vocals: Path | None = None,
    verify_pitch: bool = False, melody_only: bool = False,
) -> AnalysisResult:
    with TemporaryDirectory(prefix="noteflow-", dir=workdir) as directory:
        directory = Path(directory)
        if progress:
            progress("正在解码音轨…")
        source = MediaInfo(vocals, 0, "pcm_s16le", "wav") if vocals is not None else media
        audio = normalize(source, directory, ffmpeg, cancel=cancel)
        check_cancelled(cancel)
        if progress:
            progress("正在识别音高…")
        candidate_overlap = None
        if melody_only:
            notes, candidate_overlap = transcribe_melody(audio, cancel, isolated=vocals is not None)
        else:
            notes = transcribe(audio)
        check_cancelled(cancel)
        # In a crowded mix pYIN can follow the bass instead of the lead.
        if vocals is not None or (verify_pitch and (candidate_overlap or 0) <= HEAVY_OVERLAP):
            if progress:
                progress("正在复核八度…")
            notes = refine_octaves(audio, notes, cancel, isolated=vocals is not None)
        beat = BeatEstimate()
        if find_beats:
            if progress:
                progress("正在估计节奏…")
            mix = normalize(media, directory, ffmpeg, cancel=cancel, filename="mix.wav") if vocals else audio
            beat = estimate(mix)
        check_cancelled(cancel)
        return AnalysisResult(media, audio.duration_s, notes, beat, candidate_overlap)
