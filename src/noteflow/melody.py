"""Decode a continuous lead with explicit silence and evidence-based boundaries."""

from threading import Event

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks

from .options import AnalysisOptions
from .process import check_cancelled


def _pitch_path(frames, onsets, rest_scores, cancel):
    count, rest = frames.shape
    distance = np.abs(np.arange(rest)[:, None] - np.arange(rest))
    costs = np.zeros((rest + 1, rest + 1), dtype=np.float32)
    costs[:rest, :rest] = 1.5 + np.minimum(0.12 * distance, 1.8)
    costs[:rest, rest] = 1.2
    costs[rest, :rest] = 1.5
    states = np.arange(rest + 1)
    costs[states, states] = 0
    changed = states[:, None] != states
    emissions = np.log(np.maximum(np.column_stack((frames, rest_scores)), 0.001))
    attacks = np.column_stack((2.0 * np.maximum(onsets - 0.35, 0), np.zeros(count)))
    scores = np.full(rest + 1, -np.inf)
    scores[rest] = 0
    previous = np.empty((count, rest + 1), dtype=np.int16)
    for index, (emission, attack) in enumerate(zip(emissions, attacks)):
        if index % 256 == 0:
            check_cancelled(cancel)
        options = scores[:, None] - costs + changed * attack
        best = options.argmax(axis=0)
        previous[index] = best
        scores = options[best, states] + emission
    path = np.empty(count, dtype=np.int16)
    state = int(scores.argmax())
    for index in range(count - 1, -1, -1):
        path[index] = state
        state = previous[index, state]
    return path


def _runs(path):
    cuts = np.r_[0, np.flatnonzero(path[1:] != path[:-1]) + 1, len(path)]
    return list(zip(cuts[:-1], cuts[1:]))


def melody_events(frames, onsets, rms, times, midi_offset, *, isolated, cancel,
                  options: AnalysisOptions | None = None, attacks=None, pitch_attacks=None):
    if not len(frames):
        return []
    frames = np.nan_to_num(np.asarray(frames, dtype=float), nan=0, posinf=0, neginf=0)
    onsets = np.clip(np.nan_to_num(onsets, nan=0), 0, 1)
    frames = np.clip(frames, 0, 1)
    dt = float(np.median(np.diff(times)))
    if dt <= 0 or len(times) != len(frames) + 1 or len(rms) != len(frames):
        raise ValueError("Invalid analysis timebase")
    if options is not None:
        pitches = np.arange(frames.shape[1]) + midi_offset
        frames[:, (pitches < options.pitch_min) | (pitches > options.pitch_max)] = 0

    # Smooth only frame-sized glitches; leave onset evidence intact.
    support = median_filter(frames, size=(3, 1), mode="nearest")
    if not isolated and frames.shape[1] > 24:
        active = frames >= 0.30
        higher = np.maximum.accumulate(frames[:, ::-1], axis=1)[:, ::-1]
        higher = np.concatenate((higher[:, 7:], np.zeros((len(frames), 7))), axis=1)
        underneath = active & (higher > 0.45) & (frames + 0.04 < higher)
        backing = underneath.sum(axis=0) / (active.sum(axis=0) + 24)
        support *= 1 - 0.75 * backing
        # Follow the local register of the predominant line, not a permanent
        # penalty attached to a pitch class. This can move with a new phrase.
        strongest = support.argmax(axis=1).astype(float)
        reliable = support.max(axis=1) >= 0.45
        if np.any(reliable):
            indices = np.arange(len(support))
            strongest = np.interp(indices, indices[reliable], strongest[reliable])
            window = max(3, round(4.0 / dt) | 1)
            center = median_filter(strongest, size=window, mode="nearest")
            distance = np.abs(np.arange(frames.shape[1])[None, :] - center[:, None])
            support *= np.maximum(0.40, np.exp(-0.13 * np.maximum(distance - 9, 0)))
    quiet_level = max(1e-8, 0.035 * float(np.quantile(rms, 0.95)))
    quiet = np.clip(1 - rms / quiet_level, 0, 1)
    rest_scores = 0.30 + 0.60 * quiet
    path = _pitch_path(support, onsets, rest_scores, cancel)
    rest = frames.shape[1]

    # Bridge a short confidence hole only in the SAME pitch, with acoustic
    # support and no new attack. A genuine quiet gap remains a rest.
    runs = _runs(path)
    for index, (start, end) in enumerate(runs):
        if index == 0 or index == len(runs) - 1 or path[start] != rest:
            continue
        pitch = path[start - 1]
        if (pitch == path[end] and pitch != rest and times[end] - times[start] <= 0.065
                and np.min(rms[start:end]) >= quiet_level
                and np.mean(frames[start:end, pitch]) >= 0.16
                and np.max(onsets[max(0, start - 1):min(len(path), end + 2), pitch]) < 0.60):
            path[start:end] = pitch

    events = []
    min_frames = max(2, round(0.035 / dt))
    for start, end in _runs(path):
        pitch = path[start]
        if pitch == rest:
            continue
        duration = times[end] - times[start]
        attack = float(np.max(onsets[max(0, start - 1):min(end, start + 3), pitch]))
        if duration < 0.045 or (duration < 0.075 and attack < 0.55):
            continue
        peaks, _ = find_peaks(onsets[start:end, pitch], height=0.60, prominence=0.20,
                              distance=min_frames)
        splits = peaks[(peaks >= min_frames) & (peaks <= end - start - min_frames)] + start
        if attacks is not None:
            radius = max(1, round(0.035 / dt))
            splits = np.asarray([split for split in splits
                                 if np.max(attacks[max(0, split - radius):split + radius + 1]) >= 0.30], dtype=int)
        if pitch_attacks is not None:
            radius = max(1, round(0.045 / dt))
            splits = np.asarray([split for split in splits
                                 if np.max(pitch_attacks[max(0, split - radius):split + radius + 1, pitch]) >= 0.30], dtype=int)
        for first, last in zip(np.r_[start, splits], np.r_[splits, end]):
            strength = float(frames[first:last, pitch].mean())
            events.append((float(times[first]), float(times[last]), int(pitch) + midi_offset, strength))
    check_cancelled(cancel)
    return events
