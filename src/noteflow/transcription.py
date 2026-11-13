"""Adapt Basic Pitch output to time-based NoteFlow events."""

import math
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from threading import Event

from .errors import NoteFlowError
from .media import AudioAsset, SAMPLE_RATE
from .notes import NoteEvent
from .process import Cancelled, check_cancelled
from .options import AnalysisOptions
from .score import monophonic


@lru_cache(maxsize=1)
def _load_model():
    try:
        import basic_pitch
        from basic_pitch.inference import Model, predict

        model_path = Path(basic_pitch.__file__).parent / "saved_models" / "icassp_2022" / "nmp.onnx"
        import onnxruntime as ort
        session = ort.SessionOptions()
        session.intra_op_num_threads = 4
        session.inter_op_num_threads = 1
        model = Model.__new__(Model)
        model.model_type = Model.MODEL_TYPES.ONNX
        model.model = ort.InferenceSession(str(model_path), sess_options=session, providers=["CPUExecutionProvider"])
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


def _predict(audio: AudioAsset, minimum_note_ms: float, cancel: Event | None = None):
    if not audio.has_signal:
        raise NoteFlowError("NO_NOTES", "transcribe", "音轨为空或静音，请选择有声音的片段。")
    model, _ = _load_model()
    try:
        import numpy as np
        from basic_pitch.constants import AUDIO_N_SAMPLES, FFT_HOP, ANNOTATIONS_FPS
        from basic_pitch.inference import get_audio_input, unwrap_output
        from basic_pitch.note_creation import model_output_to_notes

        # Keep the model's overlapping-window timebase and check cancellation
        # between windows rather than at the end of a whole song.
        overlap_frames = 30
        overlap = overlap_frames * FFT_HOP
        output = {key: [] for key in ("note", "onset", "contour")}
        for window, _, length in get_audio_input(audio.path, overlap, AUDIO_N_SAMPLES - overlap):
            check_cancelled(cancel)
            for key, value in model.predict(window).items():
                output[key].append(value)
        check_cancelled(cancel)
        output = {key: unwrap_output(np.concatenate(values), length, overlap_frames)
                  for key, values in output.items()}
        _, events = model_output_to_notes(
            output, onset_thresh=0.5, frame_thresh=0.3,
            min_note_len=round(minimum_note_ms / 1000 * ANNOTATIONS_FPS),
            include_pitch_bends=False,
        )
        return output, _convert_events(events, audio.duration_s)
    except Cancelled:
        raise
    except Exception as exc:
        raise NoteFlowError("INFERENCE_FAILED", "transcribe", "音高识别失败，请尝试其他片段。") from exc


def _require_notes(notes: tuple[NoteEvent, ...]) -> tuple[NoteEvent, ...]:
    if not notes:
        raise NoteFlowError("NO_NOTES", "transcribe", "未识别到可靠音符，请尝试更清晰的单声部片段。")
    return notes


def transcribe(audio: AudioAsset) -> tuple[NoteEvent, ...]:
    _, notes = _predict(audio, minimum_note_ms=127.70)
    return _require_notes(notes)


def transcribe_melody(
    audio: AudioAsset, cancel: Event | None = None, *, isolated: bool = False,
    options: AnalysisOptions | None = None,
    pitch_python: str = "",
) -> tuple[tuple[NoteEvent, ...], float]:
    check_cancelled(cancel)
    output, candidates = _predict(audio, minimum_note_ms=50, cancel=cancel)
    check_cancelled(cancel)
    import librosa
    import numpy as np
    from basic_pitch.constants import FFT_HOP
    from basic_pitch.note_creation import MIDI_OFFSET, model_frames_to_time

    from .melody import melody_events

    frames, onsets = output["note"], output["onset"]
    times = model_frames_to_time(len(frames) + 1)
    samples, _ = librosa.load(audio.path, sr=SAMPLE_RATE, mono=True)
    rms = librosa.feature.rms(y=samples, frame_length=1024, hop_length=FFT_HOP)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=SAMPLE_RATE, hop_length=FFT_HOP)
    aligned_rms = np.interp(times[:-1], rms_times, rms)
    flux = librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE, hop_length=FFT_HOP)
    flux_times = librosa.frames_to_time(np.arange(len(flux)), sr=SAMPLE_RATE, hop_length=FFT_HOP)
    attacks = np.interp(times[:-1], flux_times, flux)
    attacks = np.clip(attacks / max(1e-8, float(np.quantile(attacks, 0.95))), 0, 1)
    pitch_attacks = _pitch_attacks(samples, SAMPLE_RATE, FFT_HOP, times[:-1], MIDI_OFFSET, frames.shape[1])
    candidate_melody = monophonic(candidates)
    competing = (len(candidates) - len(candidate_melody)) / max(1, len(candidates))
    if pitch_python:
        from .pitch import estimate_pitch
        options = options or AnalysisOptions()
        pitch_times, f0, confidence, _ = estimate_pitch(audio, pitch_python, options, cancel)
        midi = librosa.hz_to_midi(np.maximum(f0, 1))
        midi = np.interp(times[:-1], pitch_times, midi)
        confidence = np.interp(times[:-1], pitch_times, confidence)
        bins = np.arange(frames.shape[1]) + MIDI_OFFSET
        evidence = np.exp(-0.5 * ((midi[:, None] - bins) / 0.45) ** 2)
        # Agreement strengthens a candidate, disagreement leaves the AMT
        # evidence available. F0 alone cannot select a voice in a mixture.
        weight = np.clip((confidence - 0.35) / 0.45, 0, 1)[:, None]
        if not isolated and competing > 0.3:
            # On a mixture, a confident bass F0 is still the wrong target.
            # Compare with the contextual lead, not the loudest individual
            # frame: a bass transient can win a frame without winning a phrase.
            baseline = melody_events(frames, onsets, aligned_rms, times, MIDI_OFFSET,
                                     isolated=False, cancel=cancel, options=options,
                                     attacks=attacks, pitch_attacks=pitch_attacks)
            leader = np.full(len(frames), np.nan)
            for start, end, pitch, _ in baseline:
                leader[(times[:-1] >= start) & (times[:-1] < end)] = pitch
            weight *= (np.abs(midi - leader) <= 1.0)[:, None]
        frames = frames * (1 - 0.35 * weight) + evidence * (0.45 * weight)
    events = melody_events(frames, onsets, aligned_rms, times, MIDI_OFFSET,
                           isolated=isolated, cancel=cancel, options=options, attacks=attacks,
                           pitch_attacks=pitch_attacks)
    notes = _convert_events(events, audio.duration_s)
    # A polyphonic fallback would silently put the accompaniment back in.
    return _require_notes(notes), competing


def _pitch_attacks(samples, sample_rate, hop, times, midi_offset, pitch_count):
    """Measure a fresh attack in a pitch's harmonics, not the whole mix."""
    import librosa
    import numpy as np

    spectrum = np.abs(librosa.stft(samples, n_fft=2048, hop_length=hop))
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=2048)
    source_times = librosa.frames_to_time(np.arange(spectrum.shape[1]), sr=sample_rate, hop_length=hop)
    evidence = np.zeros((len(times), pitch_count))
    lag = max(1, round(.045 * sample_rate / hop))
    for pitch in range(pitch_count):
        fundamental = float(librosa.midi_to_hz(pitch + midi_offset))
        envelope = np.zeros(spectrum.shape[1])
        for harmonic in (1, 2, 3):
            frequency = fundamental * harmonic
            width = max(sample_rate / 2048, frequency * .025)
            band = np.abs(frequencies - frequency) <= width
            if np.any(band):
                envelope += spectrum[band].sum(axis=0) / harmonic
        previous = np.r_[np.zeros(lag), envelope[:-lag]]
        floor = max(1e-8, .05 * float(np.quantile(envelope, .95)))
        growth = np.clip((envelope - previous) / np.maximum(envelope, floor), 0, 1)
        evidence[:, pitch] = np.interp(times, source_times, growth)
    return evidence


def refine_octaves(audio: AudioAsset, notes: tuple[NoteEvent, ...],
                   cancel: Event | None = None, *, isolated: bool = False,
                   options: AnalysisOptions | None = None) -> tuple[NoteEvent, ...]:
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
            in_range = options is None or options.pitch_min <= proposed <= options.pitch_max
            if offset and in_range and np.count_nonzero(np.abs(center - proposed) <= 0.75) >= 2 * len(center) / 3:
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
