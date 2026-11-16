"""Generate small repairs from acoustic evidence, never from free-form advice."""

from dataclasses import dataclass, replace

import numpy as np

from .options import AnalysisOptions
from .process import check_cancelled


@dataclass(frozen=True, slots=True)
class Evidence:
    times: np.ndarray
    frames: np.ndarray
    onsets: np.ndarray
    attacks: np.ndarray
    rms: np.ndarray
    midi_offset: int
    f0_midi: np.ndarray | None = None
    f0_confidence: np.ndarray | None = None


def collect_evidence(audio, options, pitch_python="", cancel=None):
    import librosa
    from basic_pitch.constants import FFT_HOP
    from basic_pitch.note_creation import MIDI_OFFSET, model_frames_to_time

    from .media import SAMPLE_RATE
    from .transcription import _predict, _pitch_attacks

    output, _ = _predict(audio, minimum_note_ms=50, cancel=cancel)
    check_cancelled(cancel)
    frames, onsets = output["note"], output["onset"]
    times = model_frames_to_time(len(frames))
    samples, _ = librosa.load(audio.path, sr=SAMPLE_RATE, mono=True)
    rms = librosa.feature.rms(y=samples, frame_length=1024, hop_length=FFT_HOP)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=SAMPLE_RATE, hop_length=FFT_HOP)
    attacks = _pitch_attacks(samples, SAMPLE_RATE, FFT_HOP, times, MIDI_OFFSET, frames.shape[1])
    midi = confidence = None
    if pitch_python:
        from .pitch import estimate_pitch
        pt, frequency, confidence, _ = estimate_pitch(audio, pitch_python, options, cancel)
        midi = np.interp(times, pt, librosa.hz_to_midi(np.maximum(frequency, 1)))
        confidence = np.interp(times, pt, confidence)
    check_cancelled(cancel)
    return Evidence(times, frames, onsets, attacks, np.interp(times, rms_times, rms),
                    MIDI_OFFSET, midi, confidence)


class LocalRepair:
    def __init__(self, load_evidence, options=AnalysisOptions(), *, start_s=0, end_s=120):
        self.load_evidence = load_evidence
        self.options = options
        self.start_s, self.end_s = start_s, end_s
        self.evidence = None

    def __call__(self, notes, issues, cancel=None):
        actionable = [i for i in issues if i.kind in {"pitch", "octave", "rhythm", "fragmentation"}]
        if not actionable:
            return notes
        if self.evidence is None:
            self.evidence = self.load_evidence(cancel)
        evidence = self.evidence
        times, frames = evidence.times, evidence.frames
        result, changed = list(notes), 0
        floor = max(1e-8, 0.05 * float(np.quantile(evidence.rms, .95)))

        def column(pitch):
            index = pitch - evidence.midi_offset
            return index if 0 <= index < frames.shape[1] else None

        def eligible(note, kind):
            return (self.start_s <= note.start_s and note.end_s <= self.end_s
                    and any(i.kind == kind and i.start_s <= (note.start_s + note.end_s) / 2 <= i.end_s
                            for i in actionable))

        for index, note in enumerate(result):
            check_cancelled(cancel)
            if changed >= 8:
                break
            col = column(note.midi)
            if col is None:
                continue
            center = (times >= note.start_s + .025) & (times < note.end_s - .025)
            if np.count_nonzero(center) < 4:
                continue
            octave = eligible(note, "octave")
            if octave or eligible(note, "pitch"):
                alternatives = [note.midi + step for step in ((-12, 12) if octave else (-2, -1, 1, 2))
                                if self.options.pitch_min <= note.midi + step <= self.options.pitch_max
                                and column(note.midi + step) is not None]
                if alternatives:
                    target = max(alternatives, key=lambda p: float(frames[center, column(p)].mean()))
                    support = frames[center, column(target)]
                    original = frames[center, col]
                    reliable = (float(support.mean()) >= .60 and
                                np.mean((support >= .45) & (support > original + .12)) >= .75)
                    if evidence.f0_midi is not None:
                        reliable &= np.mean((np.abs(evidence.f0_midi[center] - target) < .65)
                                            & (evidence.f0_confidence[center] >= .65)) >= .70
                    else:
                        reliable &= float(support.mean()) >= .75
                    # In a mixture, octave evidence can be a bass or harmony.
                    # Require agreement with nearby lead notes before moving it.
                    if octave and self.options.target != "vocal":
                        neighbors = [n.midi for n in notes[max(0, index - 2):index] + notes[index + 1:index + 3]
                                     if min(abs(n.start_s - note.end_s), abs(note.start_s - n.end_s)) < 1.0]
                        reliable &= bool(neighbors) and abs(target - float(np.median(neighbors))) <= 7
                    if reliable:
                        result[index] = replace(note, midi=target, strength=float(support.mean()))
                        changed += 1
                        continue
            if eligible(note, "rhythm"):
                region = np.flatnonzero((times >= max(self.start_s, note.start_s - .08))
                                        & (times <= note.start_s + .08))
                if len(region):
                    peaks = evidence.onsets[region, col] * evidence.attacks[region, col]
                    best = int(region[int(peaks.argmax())])
                    proposed = float(times[best])
                    old = int(np.argmin(np.abs(times - note.start_s)))
                    before = result[index - 1].end_s if index else self.start_s
                    if (evidence.onsets[best, col] >= .60 and evidence.attacks[best, col] >= .45
                            and peaks.max() > evidence.onsets[old, col] * evidence.attacks[old, col] + .15
                            and before <= proposed <= note.end_s - .08 and abs(proposed - note.start_s) >= .02):
                        result[index] = replace(note, start_s=proposed)
                        changed += 1

        merged = []
        for note in result:
            check_cancelled(cancel)
            previous = merged[-1] if merged else None
            if (previous is not None and changed < 8 and previous.midi == note.midi
                    and 0 <= note.start_s - previous.end_s <= .12
                    and self.start_s <= previous.start_s and note.end_s <= self.end_s
                    and (eligible(previous, "fragmentation") or eligible(note, "fragmentation"))):
                col = column(note.midi)
                bridge = (times >= previous.end_s - .02) & (times <= note.start_s + .02)
                onset = (times >= note.start_s - .05) & (times <= note.start_s + .05)
                if (col is not None and bridge.any() and onset.any()
                        and np.min(evidence.rms[bridge]) > floor
                        and np.mean(frames[bridge, col]) >= .30
                        and np.max(evidence.onsets[onset, col]) < .55
                        and np.max(evidence.attacks[onset, col]) < .30):
                    merged[-1] = replace(previous, end_s=note.end_s)
                    changed += 1
                    continue
            merged.append(note)
        return tuple(merged)
