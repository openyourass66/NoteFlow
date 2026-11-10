import mido
import pytest

from noteflow.export import export_score, write_midi
from noteflow.notes import NoteEvent
from noteflow.rhythm import from_beats
from noteflow.score import BAR, ScoreSettings, build_score, rekey, to_text


def note(index, start, end, midi, strength=0.5):
    return NoteEvent(str(index), start, end, midi, strength, 80)


def test_jianpu_renders_rest_and_cross_bar_tie():
    score = build_score((note(1, 0, 0.5, 60), note(2, 0.5, 0.75, 62),
                         note(3, 1, 1.25, 75), note(4, 1.75, 2.25, 67)), ScoreSettings())
    assert to_text(score) == "1=C  4/4  BPM=120\n1[1] 2[1/2] 0[1/2] ♭3^[1/2] 0[1] 5[1/2]~ | 5[1/2] 0[2] 0[1] 0[1/2]\n"
    assert all(sum(t.duration_tick for t in bar) == BAR for bar in score.measures)
    assert score.measures[0][-1].note_id == score.measures[1][0].note_id == "4"


def test_first_beat_shift_and_rekey_preserve_absolute_pitch():
    original = build_score((note(1, 0, 0.5, 60),), ScoreSettings(first_beat_s=0.3))
    changed = rekey(original, 2, revision=3)
    assert changed.grid is original.grid
    assert changed.grid.shift_ticks == BAR
    assert changed.grid.notes[0].start_tick == 1680
    assert changed.revision == 3
    assert "♭7v" in to_text(changed)


def test_deterministic_overlaps_and_grid_collision():
    events = (note(1, 0, 0.02, 60), note(2, 0.02, 0.03, 62, 0.8),
              note(3, 0, 0.019, 64, 0.4), note(4, 0.0625, 0.25, 60), note(5, 0.25, 0.5, 60))
    score = build_score(events, ScoreSettings())
    assert [(n.id, n.start_tick, n.duration_tick) for n in score.grid.notes] == [
        ("2", 0, 120), ("4", 120, 120), ("5", 240, 240),
    ]
    assert (score.grid.overlap_drops, score.grid.merged) == (1, 1)


def test_melody_keeps_connected_attacks_over_a_stronger_sustained_bass():
    notes = (note(1, 0, 1.2, 43, 0.95), note(2, 0, 0.35, 65),
             note(3, 0.3, 0.65, 67), note(4, 0.6, 0.95, 69), note(5, 0.9, 1.2, 67))
    score = build_score(notes, ScoreSettings())
    assert [n.midi for n in score.grid.notes] == [65, 67, 69, 67]
    assert [n.end_s for n in score.melody] == [0.3, 0.6, 0.9, 1.2]
    assert score.grid.overlap_drops == 1


def test_melody_preview_keeps_original_note_times_with_a_pickup(tmp_path):
    score = build_score((note(1, 0.13, 0.42, 60), note(2, 0.49, 0.68, 64)),
                        ScoreSettings(bpm=100, first_beat_s=0.35))
    assert score.grid.shift_ticks == BAR
    path = tmp_path / "preview.mid"
    write_midi(score, 0, path, original_timing=True)
    elapsed, times, pitches = 0, [], []
    for message in mido.MidiFile(path):
        elapsed += message.time
        if message.type in {"note_on", "note_off"}:
            times.append(elapsed)
            pitches.append(message.note)
    assert times == pytest.approx([0.13, 0.42, 0.49, 0.68], abs=0.001)
    assert pitches == [60, 60, 64, 64]


def test_empty_score_and_unreliable_beat_use_safe_defaults():
    assert to_text(build_score((), ScoreSettings())) == "1=C  4/4  BPM=120\n0[4]\n"
    assert from_beats(80, (0, 0.75, 1.5)).bpm == 120
    estimate = from_beats(80, (0.1, 0.85, 1.6, 2.35))
    assert (estimate.reliable, estimate.bpm, estimate.first_beat_s) == (True, 80, 0.1)


def test_midi_export_matches_score_and_can_replace_only_with_permission(tmp_path):
    score = build_score((note(1, 0, 0.5, 60), note(2, 0.5, 0.75, 60), note(3, 1.75, 2.25, 67)),
                        ScoreSettings(tonic_pc=2))
    midi_path, txt_path = tmp_path / "旋律.mid", tmp_path / "旋律.txt"
    export_score(score, 24, midi_path, midi=True, overwrite=False)
    export_score(score, 24, txt_path, midi=False, overwrite=False)
    assert txt_path.read_text(encoding="utf-8") == to_text(score)
    with pytest.raises(FileExistsError):
        export_score(score, 40, midi_path, midi=True, overwrite=False)
    midi = mido.MidiFile(midi_path)
    assert (midi.type, midi.ticks_per_beat) == (0, 480)
    track = midi.tracks[0]
    assert track[0].tempo == 500000
    assert (track[1].numerator, track[1].denominator) == (4, 4)
    assert (track[2].key, track[3].program) == ("D", 24)
    tick, events = 0, []
    for message in track:
        tick += message.time
        if message.type in {"note_on", "note_off"}:
            events.append((tick, message.type, message.note))
    assert events == [(0, "note_on", 60), (480, "note_off", 60), (480, "note_on", 60),
                      (720, "note_off", 60), (1680, "note_on", 67), (2160, "note_off", 67)]
    assert tick == BAR * len(score.measures)
    export_score(score, 40, midi_path, midi=True, overwrite=True)
    assert mido.MidiFile(midi_path).tracks[0][3].program == 40
    assert set(tmp_path.iterdir()) == {midi_path, txt_path}
