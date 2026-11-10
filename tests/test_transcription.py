from noteflow.media import AudioAsset
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
