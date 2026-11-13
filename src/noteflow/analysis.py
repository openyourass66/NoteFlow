"""Run the local transcription pipeline and own its temporary files."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from .media import MediaInfo, normalize, probe
from .notes import NoteEvent
from .options import AnalysisOptions, UncertainRegion
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
    options: AnalysisOptions = AnalysisOptions()
    uncertain: tuple[UncertainRegion, ...] = ()


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
    options: AnalysisOptions | None = None, pitch_python: str = "",
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
        isolated = (options.target == "vocal") if options else vocals is not None
        if melody_only:
            notes, candidate_overlap = transcribe_melody(audio, cancel, isolated=isolated,
                                                       options=options, pitch_python=pitch_python)
        else:
            notes = transcribe(audio)
        check_cancelled(cancel)
        # In a crowded mix pYIN can follow the bass instead of the lead.
        if not pitch_python and (isolated or (verify_pitch and (candidate_overlap or 0) <= HEAVY_OVERLAP)):
            if progress:
                progress("正在复核八度…")
            notes = refine_octaves(audio, notes, cancel, isolated=isolated, options=options)
        beat = BeatEstimate()
        if find_beats:
            if progress:
                progress("正在估计节奏…")
            mix = normalize(media, directory, ffmpeg, cancel=cancel, filename="mix.wav") if vocals else audio
            beat = estimate(mix)
        check_cancelled(cancel)
        uncertain = tuple(UncertainRegion(n.start_s, n.end_s, "音高证据偏弱，请对照原声")
                          for n in notes if n.strength is not None and n.strength < 0.40)
        return AnalysisResult(media, audio.duration_s, notes, beat, candidate_overlap,
                              options or AnalysisOptions(), uncertain)
