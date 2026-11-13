"""Generate reproducible local listening artifacts without assuming a ground truth."""

import argparse
from dataclasses import asdict
import hashlib
import json
import sys
from pathlib import Path
from threading import Event
from time import perf_counter

from noteflow.analysis import analyze_media
from noteflow.desktop_settings import _default_tools
from noteflow.export import write_midi
from noteflow.media import probe
from noteflow.options import AnalysisOptions
from noteflow.project import Project, save_project
from noteflow.score import ScoreSettings, build_score, to_text
from noteflow.synthesis import render_preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--without-pitch", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tools = _default_tools()
    start = perf_counter()
    analysis = analyze_media(probe(args.source, tools.ffprobe), ffmpeg=tools.ffmpeg,
                             find_beats=True, melody_only=True, options=AnalysisOptions(),
                             pitch_python="" if args.without_pitch else tools.pitch_python,
                             progress=lambda message: print(message, flush=True))
    elapsed = perf_counter() - start
    score = build_score(analysis.notes, ScoreSettings(analysis.beat.bpm, analysis.beat.first_beat_s))
    render_preview(score, 0, Path(tools.soundfont), args.output / "演奏.wav", tools.fluidsynth, Event())
    write_midi(score, 0, args.output / "主旋律.mid")
    (args.output / "简谱.txt").write_text(to_text(score), encoding="utf-8")
    save_project(Project(args.source.name, analysis.media, analysis, score, None),
                 args.output / "主旋律.noteflow", tools.ffmpeg)
    gaps = [b.start_s - a.end_s for a, b in zip(score.melody, score.melody[1:])]
    report = {
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "duration_s": analysis.duration_s, "analysis_seconds": elapsed,
        "options": asdict(analysis.options),
        "auxiliary_pitch": bool(tools.pitch_python and not args.without_pitch),
        "notes": [asdict(note) for note in score.melody],
        "uncertain": [asdict(region) for region in analysis.uncertain],
        "note_count": len(score.melody),
        "sounding_seconds": sum(n.end_s - n.start_s for n in score.melody),
        "gaps_under_80ms": sum(0 < gap < 0.08 for gap in gaps),
        "accuracy": None,
        "evaluation_note": "未提供人工主旋律标注；时长和音符数量仅用于诊断，不代表准确率。",
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("notes", "uncertain")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
