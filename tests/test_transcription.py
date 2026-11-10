from noteflow.transcription import _convert_events


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
