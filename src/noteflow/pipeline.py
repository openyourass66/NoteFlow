"""Choose analysis input from explicit intent, never from polyphony alone."""

from dataclasses import dataclass
from pathlib import Path

from .analysis import AnalysisResult, analyze_media
from .errors import NoteFlowError
from .media import MediaInfo, native_track_index
from .options import AnalysisOptions
from .separation import STEM_LABELS, Stems, separate


@dataclass(frozen=True, slots=True)
class PipelineResult:
    analysis: AnalysisResult
    stems: Stems | None = None


def run_pipeline(media, options: AnalysisOptions, *, ffmpeg="ffmpeg", demucs_python="",
                 pitch_python="", stems: Stems | None = None, destination: Path | None = None,
                 native_tracks: tuple[MediaInfo, ...] = (),
                 workdir=None, cancel=None, progress=None) -> PipelineResult:
    track = options.track
    native_index = native_track_index(track)
    source = None
    if native_index is not None:
        if native_index >= len(native_tracks):
            raise NoteFlowError("TRACK_UNAVAILABLE", "transcribe", "所选音轨不可用，请重新选轨。")
        media = native_tracks[native_index]
    elif track in STEM_LABELS:
        if stems is None and options.source in ("auto", "separated"):
            if not demucs_python or destination is None:
                raise NoteFlowError("TOOL_NOT_FOUND", "separate",
                                    "请配置分离环境；清唱或独奏也可选择“直接识别原曲”。")
            if progress:
                progress("正在分离人声与伴奏…")
            stems = separate(media, destination, python=demucs_python, ffmpeg=ffmpeg, cancel=cancel)
        source = stems.tracks().get(track) if stems else None
        if source is None:
            raise NoteFlowError("TRACK_UNAVAILABLE", "transcribe", "所选分轨不可用，请重新识别分轨。")
    analysis = analyze_media(media, ffmpeg=ffmpeg, find_beats=True, workdir=workdir,
                             cancel=cancel, progress=progress, vocals=source, verify_pitch=True,
                             melody_only=True, options=options, pitch_python=pitch_python,
                             accompaniment_stems=stems if track == "accompaniment" else None)
    return PipelineResult(analysis, stems)
