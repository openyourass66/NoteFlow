import numpy as np
import pytest

from noteflow.media import AudioAsset
from noteflow.melody import melody_events
from noteflow.transcription import _convert_events, refine_octaves
from poc.fixtures import write_wave


def test_conversion_clips_notes_and_keeps_overlaps_for_score_building():
    events = [
        (1.0, 2.5, 64, None, []),
        (-0.25, 1.5, 60, 1.4, []),
        (0.5, 1.5, 67, -0.4, []),
        (0.0, float("nan"), 60, 0.5, []),
        (0.5, 1.0, 128, 0.5, []),
        (3.0, 4.0, 60, 0.5, []),
    ]
    notes = _convert_events(events, duration_s=2.0)
    assert [(note.id, note.start_s, note.end_s, note.midi) for note in notes] == [
        ("n2", 0.0, 1.5, 60), ("n3", 0.5, 1.5, 67), ("n1", 1.0, 2.0, 64),
    ]
    assert [(note.strength, note.velocity) for note in notes] == [(1.0, 127), (0.0, 1), (None, 80)]


def test_fundamental_corrects_a_false_octave_and_preserves_a_real_drop(tmp_path):
    path = tmp_path / "octaves.wav"
    write_wave(path, 1.6, [(0.1, 0.75, 69), (0.8, 1.5, 57)])
    notes = _convert_events([(0.1, 0.75, 57, 0.8), (0.8, 1.5, 57, 0.8)], duration_s=1.6)
    corrected = refine_octaves(AudioAsset(path, 1.6, True), notes)
    assert [(n.start_s, n.end_s, n.midi) for n in corrected] == [(0.1, 0.75, 69), (0.8, 1.5, 57)]


def test_frame_decoder_splits_reattack_and_preserves_a_real_rest_and_leap():
    frames = np.full((60, 25), 0.05)
    onsets = np.zeros_like(frames)
    frames[0:32, 12] = 0.8
    onsets[[0, 16], 12] = 0.95
    frames[42:60, 0] = 0.8
    onsets[42, 0] = 0.95
    rms = np.full(60, 0.2)
    times = np.arange(61) * 0.01

    events = melody_events(frames, onsets, rms, times, 48, isolated=True, cancel=None)

    assert [(start, end, pitch) for start, end, pitch, _ in events] == [
        (times[0], times[16], 60), (times[16], times[32], 60), (times[42], times[60], 48),
    ]


def test_confident_bass_f0_cannot_pull_the_contextual_lead_down_an_octave(tmp_path, monkeypatch):
    from noteflow import transcription, pitch
    from noteflow.notes import NoteEvent

    path = tmp_path / "lead-with-bass.wav"
    write_wave(path, 2, [(0, 1.9, 72), (.7, .9, 60)])
    frames = np.full((170, 88), .02)
    frames[:, 72 - 21] = .65
    frames[60:78, 60 - 21] = .85
    onsets = np.zeros_like(frames)
    onsets[60, 60 - 21] = .8
    candidates = (NoteEvent("lead", 0, 1.9, 72, .65, 90), NoteEvent("bass", .7, .9, 60, .85, 100))
    monkeypatch.setattr(transcription, "_predict", lambda *a, **kw: ({"note": frames.copy(), "onset": onsets}, candidates))
    monkeypatch.setattr(pitch, "estimate_pitch", lambda *a: (np.array([0, 2]), np.full(2, 261.6256), np.full(2, .99), "cpu"))
    notes, overlap = transcription.transcribe_melody(AudioAsset(path, 2, True), pitch_python="fixture")
    assert overlap == .5
    assert {note.midi for note in notes} == {72}


@pytest.mark.parametrize("has_lead", [True, False])
def test_accompaniment_uses_separate_evidence_to_follow_lead_without_losing_bass_solos(
    tmp_path, monkeypatch, has_lead,
):
    from noteflow import transcription
    from noteflow.notes import NoteEvent

    path = tmp_path / "mix.wav"
    write_wave(path, 2, [(0, 2, 45)])
    mix = AudioAsset(path, 2, True)
    bass = AudioAsset(tmp_path / "bass.wav", 2, True)
    other = AudioAsset(tmp_path / "other.wav", 2, True)
    bass_frames = np.full((170, 88), .02)
    bass_frames[:, 45 - 21] = .96
    bass_frames[:, 48 - 21] = .80
    lead_frames = np.full_like(bass_frames, .02)
    candidates = [NoteEvent("bass", 0, 2, 45, .96, 115),
                  NoteEvent("bass-overtone", 0, 2, 48, .80, 100)]
    for i, (start, end, pitch) in enumerate([(0, 52, 64), (52, 96, 57), (96, 125, 74)]):
        candidates.append(NoteEvent(f"lead-{i}", start * .012, end * .012, pitch, .55, 80))
        if has_lead:
            lead_frames[start:end, pitch - 21] = .78
    mix_frames = np.maximum(bass_frames, .71 * lead_frames)
    outputs = {mix: mix_frames, bass: bass_frames, other: lead_frames}

    def predict(asset, **_kwargs):
        frames = outputs[asset]
        return {"note": frames.copy(), "onset": np.zeros_like(frames)}, tuple(candidates)

    monkeypatch.setattr(transcription, "_predict", predict)
    original, _ = transcription.transcribe_melody(mix)
    guided, _ = transcription.transcribe_melody(mix, accompaniment_guides=(bass, other))
    assert [note.midi for note in original] == [45]
    assert [note.midi for note in guided] == ([64, 57, 74] if has_lead else [45])
    if has_lead:
        assert guided[-1].end_s < 1.6  # The low backing continues into the lead's rest.
