import numpy as np
import pytest

from noteflow.melody import melody_events
from noteflow.options import AnalysisOptions
from noteflow.process import Cancelled
from threading import Event


def decode(frames, onsets=None, rms=None, **kwargs):
    return melody_events(frames, np.zeros_like(frames) if onsets is None else onsets,
                         np.full(len(frames), 0.2) if rms is None else rms,
                         np.arange(len(frames) + 1) * 0.01, 48,
                         isolated=True, cancel=None, **kwargs)


def test_short_confidence_hole_is_joined_but_actual_silence_is_preserved():
    frames = np.full((100, 25), .03)
    frames[:, 12] = .8
    frames[40:44, 12] = .20
    assert len(decode(frames)) == 1
    frames[40:50, 12] = .02
    rms = np.full(100, .2)
    rms[40:50] = 0
    events = decode(frames, rms=rms)
    assert len(events) == 2
    assert events[0][1] <= .41 and events[1][0] >= .49


def test_model_reattacks_need_acoustic_evidence_when_available():
    frames = np.full((100, 25), .03)
    frames[:, 12] = .8
    onsets = np.zeros_like(frames)
    onsets[[20, 40, 60, 80], 12] = .95
    attacks = np.zeros(100)
    attacks[60] = 1
    events = decode(frames, onsets, attacks=attacks)
    assert [(s, e, p) for s, e, p, _ in events] == [(0, .6, 60), (.6, 1, 60)]


def test_bass_attack_does_not_retrigger_a_sustained_lead():
    from noteflow.transcription import _pitch_attacks

    sr, hop = 22050, 256
    t = np.arange(sr) / sr
    envelope = np.ones_like(t)
    envelope[(t >= .65) & (t < .72)] = 0
    lead = .2 * np.sin(2 * np.pi * 523.25 * t) * envelope
    bass = .5 * np.sin(2 * np.pi * 110 * t) * np.exp(-18 * np.maximum(t - .35, 0)) * (t >= .35)
    times = np.arange(100) * .01
    attacks = _pitch_attacks(lead + bass, sr, hop, times, 48, 25)
    assert attacks[32:40, 24].max() < .15
    assert attacks[70:78, 24].max() > .50

    frames = np.full((100, 25), .03)
    frames[:, 24] = .8
    onsets = np.zeros_like(frames)
    onsets[[35, 72], 24] = .95
    events = decode(frames, onsets, attacks=np.ones(100), pitch_attacks=attacks)
    assert [(s, e, p) for s, e, p, _ in events] == [(0, .72, 72), (.72, 1, 72)]


def test_short_strongly_attacked_note_and_real_octave_leap_survive():
    frames = np.full((100, 40), .03)
    frames[:40, 12] = .8
    frames[40:46, 14] = .9
    frames[46:, 26] = .8
    onsets = np.zeros_like(frames)
    onsets[40, 14] = .95
    onsets[46, 26] = .95
    assert [p for _, _, p, _ in decode(frames, onsets)] == [60, 62, 74]


def test_requested_range_cannot_fall_back_to_unwanted_polyphony():
    frames = np.full((100, 40), .03)
    frames[:, 2] = .9
    assert decode(frames, options=AnalysisOptions(pitch_min=60, pitch_max=84)) == []


def test_decoder_obeys_cancellation():
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        melody_events(np.ones((100, 25)), np.zeros((100, 25)), np.ones(100),
                      np.arange(101) * .01, 48, isolated=True, cancel=cancel)
