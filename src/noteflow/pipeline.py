"""Choose analysis input from explicit intent, never from polyphony alone."""

from dataclasses import dataclass
from pathlib import Path

from .analysis import AnalysisResult, analyze_media
from .errors import NoteFlowError
from .options import AnalysisOptions
from .separation import Stems, separate


@dataclass(frozen=True, slots=True)
class PipelineResult:
    analysis: AnalysisResult
    stems: Stems | None = None


def run_pipeline(media, options: AnalysisOptions, *, ffmpeg="ffmpeg", demucs_python="",
                 pitch_python="", stems: Stems | None = None, destination: Path | None = None,
                 workdir=None, cancel=None, progress=None) -> PipelineResult:
    use_stem = options.source == "separated" or (options.source == "auto" and options.target == "vocal")
    source = None
    if use_stem:
        if stems is None:
            if not demucs_python or destination is None:
                raise NoteFlowError("TOOL_NOT_FOUND", "separate",
                                    "请配置分离环境；清唱或独奏也可选择“直接识别原曲”。")
            if progress:
                progress("正在分离人声与伴奏…")
            stems = separate(media, destination, python=demucs_python, ffmpeg=ffmpeg, cancel=cancel)
        source = stems.vocals if options.target == "vocal" else stems.accompaniment
    analysis = analyze_media(media, ffmpeg=ffmpeg, find_beats=True, workdir=workdir,
                             cancel=cancel, progress=progress, vocals=source, verify_pitch=True,
                             melody_only=True, options=options, pitch_python=pitch_python)
    return PipelineResult(analysis, stems)
