"""Estimate a tempo and first-beat offset from the decoded audio."""

import math
from dataclasses import dataclass
from statistics import median

from .media import AudioAsset, SAMPLE_RATE
from .score import BPM_MAX, BPM_MIN, ScoreSettings


@dataclass(frozen=True, slots=True)
class BeatEstimate:
    bpm: float = 120
    first_beat_s: float = 0
    reliable: bool = False


def from_beats(bpm: float, beats: tuple[float, ...]) -> BeatEstimate:
    if not BPM_MIN <= bpm <= BPM_MAX or len(beats) < 4 or not all(map(math.isfinite, beats)):
        return BeatEstimate()
    intervals = [right - left for left, right in zip(beats, beats[1:])]
    interval = median(intervals)
    if min(intervals) <= 0 or median(abs(value - interval) for value in intervals) / interval > 0.12:
        return BeatEstimate()
    bpm = round(bpm, 1)
    beat_s = ScoreSettings(bpm).tempo_us / 1_000_000
    offset = math.floor((beats[0] % beat_s) * 1000) / 1000
    return BeatEstimate(bpm, offset, True)


def estimate(audio: AudioAsset) -> BeatEstimate:
    import librosa
    import numpy as np

    try:
        samples, _ = librosa.load(str(audio.path), sr=SAMPLE_RATE, mono=True)
        tempo, frames = librosa.beat.beat_track(y=samples, sr=SAMPLE_RATE, trim=False)
        bpm = np.asarray(tempo).reshape(-1)
        times = librosa.frames_to_time(frames, sr=SAMPLE_RATE)
        return from_beats(float(bpm[0]), tuple(map(float, times))) if len(bpm) else BeatEstimate()
    except Exception:
        return BeatEstimate()
