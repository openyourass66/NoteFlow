"""Decode a monophonic melody from Basic Pitch frame and onset activations."""

from threading import Event

import numpy as np
from scipy.signal import find_peaks

from .process import check_cancelled


# Basic Pitch emits one frame per 256 samples at 22,050 Hz.
MIN_NOTE_FRAMES = 7


def _pitch_path(
    frames: np.ndarray, onsets: np.ndarray, rest_scores: np.ndarray, cancel: Event | None,
) -> np.ndarray:
    """Find the highest-scoring path through pitch and rest states."""
    frame_count, rest = frames.shape
    pitches = np.arange(rest)
    states = np.arange(rest + 1)
    distance = np.abs(pitches[:, None] - pitches)

    # A change needs more evidence than continuing a note. Cap the distance
    # penalty so a strong attack can still start a real octave leap.
    costs = np.zeros((rest + 1, rest + 1), dtype=np.float32)
    costs[:rest, :rest] = 0.75 + np.minimum(0.10 * distance, 1.40)
    costs[:rest, rest] = 0.45
    costs[rest, :rest] = 0.80
    costs[states, states] = 0
    changed = states[:, None] != states

    emissions = np.log(np.maximum(np.column_stack((frames, rest_scores)), 0.001))
    attack_bonus = np.column_stack((1.6 * np.maximum(onsets - 0.30, 0), np.zeros(frame_count)))
    scores = np.full(rest + 1, -np.inf)
    scores[rest] = 0
    previous = np.empty((frame_count, rest + 1), dtype=np.int16)
    for index, (emission, attack) in enumerate(zip(emissions, attack_bonus)):
        if index % 256 == 0:
            check_cancelled(cancel)
        options = scores[:, None] - costs + changed * attack
        best = options.argmax(axis=0)
        previous[index] = best
        scores = options[best, states] + emission

    path = np.empty(frame_count, dtype=np.int16)
    state = int(scores.argmax())
    for index in range(frame_count - 1, -1, -1):
        path[index] = state
        state = previous[index, state]
    return path


def melody_events(
    frames: np.ndarray, onsets: np.ndarray, rms: np.ndarray, times: np.ndarray, midi_offset: int,
    *, isolated: bool, cancel: Event | None,
) -> list[tuple[float, float, int, float]]:
    if not len(frames):
        return []
    salience = frames
    if not isolated:
        # Downweight pitches that are repeatedly audible underneath a stronger
        # pitch so accompaniment is less likely to fill rests in the lead.
        active = frames >= 0.35
        competing = active & (frames + 0.04 < frames.max(axis=1, keepdims=True))
        salience = frames * (1 - 0.8 * competing.sum(axis=0) / (active.sum(axis=0) + 24))

    # Relative quiet helps distinguish rests from low-level reverb or noise
    # that the model still assigns a pitch.
    quiet_level = max(1e-8, 0.04 * float(np.quantile(rms, 0.95)))
    quiet = np.clip(1 - rms / quiet_level, 0, 1)
    rest_scores = 0.42 + 0.48 * quiet
    path = _pitch_path(salience, onsets, rest_scores, cancel)
    boundaries = np.r_[0, np.flatnonzero(path[1:] != path[:-1]) + 1, len(path)]
    events = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        pitch = path[start]
        if pitch == frames.shape[1] or end - start < MIN_NOTE_FRAMES:
            continue

        # The path stays on the same pitch during a repeated note. Split it
        # only at a clear reattack with enough frames on both sides.
        peaks, _ = find_peaks(onsets[start:end, pitch], height=0.65, prominence=0.18,
                              distance=MIN_NOTE_FRAMES)
        splits = peaks[(peaks >= MIN_NOTE_FRAMES) & (peaks <= end - start - MIN_NOTE_FRAMES)] + start
        cuts = np.r_[start, splits, end]
        for first, last in zip(cuts[:-1], cuts[1:]):
            strength = float(frames[first:last, pitch].mean())
            events.append((times[first], times[last], int(pitch) + midi_offset, strength))
    check_cancelled(cancel)
    return events
