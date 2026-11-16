"""Wire the local evidence, renderer and cloud reviewer into a review session."""

from pathlib import Path

from .review import run_review, save_report
from .review_audio import ReviewAudio
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

    def checkpoint(result):
        save_report(result, folder / "report.json", model=config.model, usage=reviewer.usage)

    return run_review(score.melody, analysis.duration_s, reviewer, repair, limits=limits,
                      start_s=start_s, end_s=end_s, cancel=cancel, progress=progress, checkpoint=checkpoint)
