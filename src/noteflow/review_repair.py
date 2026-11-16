"""Generate micro-edits and phrase candidates from local acoustic evidence."""

from dataclasses import dataclass, replace

import numpy as np

from .options import AnalysisOptions
from .process import check_cancelled
from .notes import NoteEvent
from .review import RepairCandidate, RepairPlan, fingerprint


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

    def propose(self, notes, issues, cancel=None):
        """Keep strict micro-edits first; also rebuild whole flagged phrases.

        Rebuilding can split, merge or insert notes. These are listening
        candidates, not trusted edits: adoption still needs comparison or an
        explicit user action, and outside notes remain exactly unchanged.
        """
        candidates, diagnostics = [], []
        signature = fingerprint(notes)
        seen = {signature}
        micro = self(notes, issues, cancel)
        if fingerprint(micro) != signature:
            candidates.append(RepairCandidate(micro, signature, self.start_s, self.end_s, "音高与起音微调"))
            seen.add(fingerprint(micro))
        for issue in issues:
            check_cancelled(cancel)
            entry = {"start_s": issue.start_s, "end_s": issue.end_s, "kind": issue.kind}
            if issue.kind == "wrong_voice":
                diagnostics.append({**entry, "summary": "声部选择需要确认；可定位音符，或调整高低声部后重新识别。"})
                continue
            if self.evidence is None:
                self.evidence = self.load_evidence(cancel)
            rebuilt = self._rebuild(notes, issue, cancel)
            if rebuilt is None:
                diagnostics.append({**entry, "summary": "本地没有找到不同且有音频支持的乐句；可定位后手动编辑。"})
                continue
            new_notes, first, last = rebuilt
            key = fingerprint(new_notes)
            if key in seen:
                diagnostics.append({**entry, "summary": "此处候选与已有音符或其他候选相同，未重复生成。"})
                continue
            seen.add(key)
            candidates.append(RepairCandidate(new_notes, signature, first, last,
                                               f"{first:.2f}–{last:.2f} 秒局部重建"))
            diagnostics.append({**entry, "summary": "已生成局部重建候选；对照通过后自动采用，也可试听后手动应用。"})
        return RepairPlan(tuple(candidates), tuple(diagnostics))

    def _rebuild(self, notes, issue, cancel):
        from .melody import melody_events

        first, last = max(self.start_s, issue.start_s), min(self.end_s, issue.end_s)
        if last <= first:
            return None
        affected = [n for n in notes if n.start_s < last and n.end_s > first
                    and n.start_s >= self.start_s and n.end_s <= self.end_s]
        if affected:
            first, last = min(first, affected[0].start_s), max(last, affected[-1].end_s)
        # A note crossing the user's selected boundary cannot be partly edited.
        for note in notes:
            if note.start_s < first < note.end_s:
                first = note.end_s
            if note.start_s < last < note.end_s:
                last = note.start_s
        if last - first < .08:
            return None
        affected = [n for n in notes if first <= n.start_s and n.end_s <= last]
        evidence = self.evidence
        indices = np.flatnonzero((evidence.times >= max(0, first - 2)) & (evidence.times <= last + 2))
        if len(indices) < 4:
            return None
        section = slice(int(indices[0]), int(indices[-1]) + 1)
        dt = float(np.median(np.diff(evidence.times)))
        times = evidence.times[section]
        frames = evidence.frames[section].copy()
        options = self.options
        # Keep the established local lead register for rhythm/continuity work.
        # Pitch and octave questions need the original configured range.
        if affected and issue.kind in {"rhythm", "fragmentation", "missing_notes"}:
            low = max(options.pitch_min, min(n.midi for n in affected) - 3)
            high = min(options.pitch_max, max(n.midi for n in affected) + 3)
            if low < high:
                options = replace(options, pitch_min=low, pitch_max=high)
        if self.options.target == "vocal" and evidence.f0_midi is not None:
            bins = np.arange(frames.shape[1]) + evidence.midi_offset
            f0 = np.exp(-.5 * ((evidence.f0_midi[section, None] - bins) / .45) ** 2)
            weight = np.clip((evidence.f0_confidence[section] - .35) / .45, 0, 1)[:, None]
            frames = frames * (1 - .35 * weight) + f0 * (.45 * weight)
        events = melody_events(frames, evidence.onsets[section], evidence.rms[section],
                               np.r_[times, times[-1] + dt], evidence.midi_offset,
                               isolated=options.target == "vocal", cancel=cancel, options=options,
                               pitch_attacks=evidence.attacks[section])
        proposed, used = [], set()
        for start, end, pitch, strength in events:
            start, end = max(first, start), min(last, end)
            if end - start < .045 or strength < .35:
                continue
            # Preserve identities and expressive velocities where a note matches.
            matches = [n for n in affected if n.id not in used and min(n.end_s, end) > max(n.start_s, start)]
            match = max(matches, key=lambda n: min(n.end_s, end) - max(n.start_s, start), default=None)
            note_id = match.id if match else f"review-{start:.6f}-{end:.6f}-{pitch}"
            used.add(note_id)
            proposed.append(NoteEvent(note_id, float(start), float(end), int(pitch), float(strength),
                                      match.velocity if match else 80))
        if not proposed:
            return None
        # Do not offer a new version for model-frame jitter alone.
        if len(proposed) == len(affected) and all(
            a.midi == b.midi and abs(a.start_s - b.start_s) < .025 and abs(a.end_s - b.end_s) < .025
            for a, b in zip(proposed, affected)
        ):
            return None
        kept = tuple(n for n in notes if not (first <= n.start_s and n.end_s <= last))
        return tuple(sorted((*kept, *proposed), key=lambda n: n.start_s)), first, last

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
