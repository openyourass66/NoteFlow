"""Controlled listening checks for a configured remote reviewer."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from .errors import NoteFlowError
from .media import MediaInfo
from .notes import NoteEvent
from .process import Cancelled, check_cancelled
from .review_audio import RATE, ReviewAudio, wav_bytes
from .review_cloud import CloudReviewer
from .score import ScoreSettings


def prepare_cases(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    notes = tuple(NoteEvent(f"c{i}", .4 + i * .85, .4 + i * .85 + .65, pitch, .9, 90)
                  for i, pitch in enumerate((60, 64, 62, 67, 65, 69, 67, 72)))
    samples = np.zeros(8 * RATE)
    for note in notes:
        first, last = round(note.start_s * RATE), round(note.end_s * RATE)
        time = np.arange(last - first) / RATE
        frequency = 440 * 2 ** ((note.midi - 69) / 12)
        envelope = np.minimum(1, np.minimum(time / .015, (note.end_s - note.start_s - time) / .04))
        phase = 2 * np.pi * frequency * time
        samples[first:last] = envelope * (np.sin(phase) + .25 * np.sin(2 * phase)) * 14000
    source = folder / "reference.wav"
    source.write_bytes(wav_bytes(samples))
    pitch = tuple(replace(n, midi=n.midi + 2) if 2 <= i <= 5 else n for i, n in enumerate(notes))
    octave = tuple(replace(n, midi=n.midi - 12) if 2 <= i <= 5 else n for i, n in enumerate(notes))
    fragmented = tuple(part for n in notes for part in (
        replace(n, id=n.id + "a", end_s=n.start_s + .20),
        replace(n, id=n.id + "b", start_s=n.start_s + .40),
    ))
    return MediaInfo(source, 0, "pcm_s16le", "wav", 8), notes, pitch, octave, fragmented


def check_reviewer(tools, config, folder, *, send=False, retain_artifacts=True, cancel=None, progress=None):
    """Six explicit requests; correctness here is not real-music accuracy."""
    folder = Path(folder)
    media, clean, pitch, octave, fragmented = prepare_cases(folder)
    report = {"model": config.model, "status": "prepared", "calls": 0, "accuracy": None,
              "scope": "8秒已知旋律；单音轨与钢琴音色对照；不代表复杂混音效果", "checks": [],
              "notes": {name: [asdict(n) for n in notes] for name, notes in
                        (("clean", clean), ("pitch", pitch), ("octave", octave), ("fragmented", fragmented))}}
    destination = folder / "calibration.json"

    def save():
        if retain_artifacts:
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    audio = ReviewAudio(media, ScoreSettings(), tools, folder / "listening", cancel)
    if retain_artifacts:
        for name, notes in (("clean", clean), ("pitch", pitch), ("octave", octave), ("fragmented", fragmented)):
            bundle, _ = audio.bundle([("A", notes)], 0, 8)
            (folder / f"{name}-comparison.wav").write_bytes(bundle)
    save()
    if not send:
        return report
    config.validate()
    reviewer = CloudReviewer(config, audio, "instrument", cancel)
    try:
        for name, notes, kinds in (("clean", clean, None), ("pitch", pitch, {"pitch"}),
                                   ("octave", octave, {"octave", "pitch"}),
                                   ("fragmented", fragmented, {"fragmentation", "rhythm", "missing_notes"})):
            check_cancelled(cancel)
            report["calls"] += 1
            if progress:
                progress(f"正在检查云端听辨能力 · 请求 {report['calls']}/6")
            verdict = reviewer.assess(notes, 0, 8)
            ok = (verdict.status == "pass") if kinds is None else (
                verdict.status == "issues" and any(i.kind in kinds for i in verdict.issues))
            report["checks"].append({"case": name, "ok": ok, "response": asdict(verdict)})
            save()
        for reverse in (False, True):
            check_cancelled(cancel)
            report["calls"] += 1
            if progress:
                progress(f"正在检查云端听辨能力 · 请求 {report['calls']}/6")
            a, b = (pitch, clean) if reverse else (clean, pitch)
            choice, summary = reviewer.compare(a, b, 0, 8)
            report["checks"].append({"case": "order_reversed" if reverse else "order_normal",
                                     "ok": choice == ("B" if reverse else "A"),
                                     "response": {"preference": choice, "summary": summary}})
            save()
        report["status"] = "passed" if all(c["ok"] for c in report["checks"]) else "failed"
    except Cancelled:
        report["status"] = "cancelled"
    except NoteFlowError as error:
        report["status"], report["error"] = "error", str(error)
    report["usage"] = reviewer.usage
    save()
    return report
