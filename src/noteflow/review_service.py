"""Wire the local evidence, renderer and cloud reviewer into a review session."""

from dataclasses import replace
from pathlib import Path

from .review import run_review
from .review_audio import ReviewAudio
from .review_audio import wav_bytes
from .review_edit import candidate_notes
from .media import MediaInfo, normalize
from .review_qwen import QwenReviewer
from .review_repair import LocalRepair, collect_evidence


def review_score(analysis, score, tools, config, folder, *, limits, start_s, end_s,
                 stem=None, cancel=None, progress=None):
    config.validate()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("正在准备原曲与钢琴演奏对照…")
    audio = ReviewAudio(analysis.media, score.settings, tools, folder / "audio", cancel)
    reviewer = QwenReviewer(config, audio, analysis.options.target, cancel)

    def evidence(flag):
        return collect_evidence(audio.evidence_audio(stem), analysis.options, tools.pitch_python, flag)

    repair = LocalRepair(evidence, analysis.options, start_s=start_s, end_s=end_s)

    result = run_review(score.melody, analysis.duration_s, reviewer, repair, limits=limits,
                        start_s=start_s, end_s=end_s, cancel=cancel, progress=progress)
    return replace(result, model=config.model, usage=reviewer.usage.copy())


def prepare_repairs(analysis, score, tools, folder, issues, *, start_s, end_s,
                    stem=None, cancel=None, progress=None):
    """Reuse existing feedback locally; no credentials or network requests."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("正在根据复核疑点重新分析原曲，生成局部候选（不调用云端）…")
    media = MediaInfo(stem, 0, "pcm_s16le", "wav") if stem else analysis.media
    def evidence(flag):
        audio = normalize(media, folder, tools.ffmpeg, cancel=flag)
        return collect_evidence(audio, analysis.options, tools.pitch_python, flag)
    return LocalRepair(evidence, analysis.options, start_s=start_s, end_s=end_s).propose(score.melody, issues, cancel)


def prepare_audition(analysis, score, candidate, tools, folder, *, cancel=None):
    candidate_notes(candidate, score.melody, analysis.duration_s)
    folder = Path(folder)
    audio = ReviewAudio(analysis.media, score.settings, tools, folder / "audio", cancel)
    first, last = max(0, candidate.start_s - .5), min(analysis.duration_s, candidate.end_s + .5)
    clips = audio.clips([("修改前", score.melody), ("候选", candidate.notes)], first, last)
    paths = []
    for index, (_, samples) in enumerate(clips):
        path = folder / f"audition-{index}.wav"
        path.write_bytes(wav_bytes(samples))
        paths.append(path)
    return tuple(paths), first, last
