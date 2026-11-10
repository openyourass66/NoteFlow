"""Adapt Basic Pitch output to time-based NoteFlow events."""

import math
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from threading import Event

from .errors import NoteFlowError
from .media import AudioAsset, SAMPLE_RATE
from .notes import NoteEvent
from .process import check_cancelled


@lru_cache(maxsize=1)
def _load_model():
    try:
        import basic_pitch
        from basic_pitch.inference import Model, predict

        model_path = Path(basic_pitch.__file__).parent / "saved_models" / "icassp_2022" / "nmp.onnx"
        model = Model(model_path)
        if model.model_type != Model.MODEL_TYPES.ONNX or model.model.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("Expected the ONNX CPU provider")
    except Exception as exc:
        raise NoteFlowError("MODEL_LOAD_FAILED", "transcribe", "无法加载 ONNX CPU 模型，请检查 Python 依赖。") from exc
    return model, predict


def _convert_events(events, duration_s: float) -> tuple[NoteEvent, ...]:
    notes = []
    for index, (start, end, pitch, amplitude, *_rest) in enumerate(events, start=1):
        if not all(map(math.isfinite, (start, end, pitch))) or int(pitch) != pitch or not 0 <= pitch <= 127:
            continue
        start, end = max(0.0, float(start)), min(duration_s, float(end))
        if end <= start:
            continue
        strength = None if amplitude is None or not math.isfinite(amplitude) else min(1.0, max(0.0, float(amplitude)))
        velocity = 80 if strength is None else 1 + round(126 * strength)
        notes.append(NoteEvent(f"n{index}", start, end, int(pitch), strength, velocity))
    return tuple(sorted(notes, key=lambda note: note.start_s))


def transcribe(audio: AudioAsset) -> tuple[NoteEvent, ...]:
    if not audio.has_signal:
        raise NoteFlowError("NO_NOTES", "transcribe", "音轨为空或静音，请选择有声音的片段。")
    model, predict = _load_model()
    try:
        _, _, events = predict(
            audio.path, model_or_model_path=model, onset_threshold=0.5,
            frame_threshold=0.3, minimum_note_length=127.70,
        )
        notes = _convert_events(events, audio.duration_s)
    except Exception as exc:
        raise NoteFlowError("INFERENCE_FAILED", "transcribe", "音高识别失败，请尝试其他片段。") from exc
    if not notes:
        raise NoteFlowError("NO_NOTES", "transcribe", "未识别到可靠音符，请尝试更清晰的单声部片段。")
    return notes


def refine_octaves(audio: AudioAsset, notes: tuple[NoteEvent, ...],
                   cancel: Event | None = None, *, isolated: bool = False) -> tuple[NoteEvent, ...]:
    """Use stable fundamental-frequency evidence to resolve octave aliases."""
    import librosa
    import numpy as np

    hop = 256
    try:
        samples, _ = librosa.load(str(audio.path), sr=SAMPLE_RATE, mono=True)
        f0, voiced, probability = librosa.pyin(
            samples, sr=SAMPLE_RATE, fmin=librosa.midi_to_hz(28), fmax=librosa.midi_to_hz(96),
            hop_length=hop, resolution=0.5,
        )
    except Exception as exc:
        raise NoteFlowError("INFERENCE_FAILED", "transcribe", "八度复核失败，请尝试其他片段。") from exc
    check_cancelled(cancel)
    pitches = librosa.hz_to_midi(np.where(voiced & (probability >= 0.65), f0, np.nan))
    frames_per_s = SAMPLE_RATE / hop
    candidates = []
    for note in notes:
        # Exclude attacks and release tails where the fundamental can be ambiguous.
        first = math.ceil((note.start_s + 0.025) * frames_per_s)
        last = math.floor((note.end_s - 0.025) * frames_per_s) + 1
        center = pitches[first:max(first, last)]
        reliable = center[np.isfinite(center)]
        target = note.midi
        if len(reliable) >= max(4, math.ceil(2 * len(center) / 3)):
            offset = round((float(np.median(reliable)) - note.midi) / 12) * 12
            proposed = note.midi + offset
            if offset and np.count_nonzero(np.abs(center - proposed) <= 0.75) >= 2 * len(center) / 3:
                target = proposed
        candidates.append((note, target))

    by_pitch: dict[int, list[NoteEvent]] = {}
    for note, target in candidates:
        if not isolated or target == note.midi:
            by_pitch.setdefault(note.midi, []).append(note)

    refined = []
    for note, target in candidates:
        if target != note.midi:
            overlaps = any(min(other.end_s, note.end_s) - max(other.start_s, note.start_s)
                           >= (note.end_s - note.start_s) / 2 for other in by_pitch.get(target, ()))
            if overlaps:
                # A competing octave in the mix may be a different instrument.
                if isolated:
                    continue
            else:
                note = replace(note, midi=target)
        refined.append(note)
    return tuple(refined)
