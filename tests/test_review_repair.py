from dataclasses import replace

import numpy as np

from noteflow.notes import NoteEvent
from noteflow.review import ReviewIssue
from noteflow.review_repair import Evidence, LocalRepair


def evidence():
    times = np.arange(0, 2, .01)
    frames = np.zeros((len(times), 88))
    frames[:, 60 - 21] = .9
    return Evidence(times, frames, np.zeros_like(frames), np.zeros_like(frames),
                    np.ones(len(times)), 21, np.full(len(times), 60), np.ones(len(times)))


def test_pitch_advice_only_changes_where_both_local_models_agree():
    notes = (NoteEvent("a", .1, .7, 62, .3, 80), NoteEvent("b", 1, 1.5, 62, .3, 80))
    e = evidence()
    issue = (ReviewIssue(0, .8, "pitch", "高了一点"),)
    repair = LocalRepair(lambda _: e)
    result = repair(notes, issue)
    assert result[0].midi == 60 and result[1] == notes[1]
    assert result[0].start_s == notes[0].start_s
    disagree = replace(e, f0_midi=np.full(len(e.times), 48))
    assert LocalRepair(lambda _: disagree)(notes, issue) == notes


def test_low_acoustic_support_cannot_be_overridden_by_cloud():
    e = evidence()
    e.frames[:] *= .3
    note = (NoteEvent("a", .1, .7, 62, .3, 80),)
    assert LocalRepair(lambda _: e)(note, (ReviewIssue(0, 1, "pitch", "非常确信改音"),)) == note


def test_same_pitch_gap_requires_sound_and_no_attack():
    notes = (NoteEvent("a", .1, .7, 60, .8, 80), NoteEvent("b", .76, 1.3, 60, .8, 80))
    issue = (ReviewIssue(0, 1.5, "fragmentation", "听起来断开"),)
    e = evidence()
    merged = LocalRepair(lambda _: e)(notes, issue)
    assert len(merged) == 1 and merged[0].end_s == 1.3
    e.rms[(e.times >= .70) & (e.times < .76)] = 0
    assert LocalRepair(lambda _: e)(notes, issue) == notes
    e.rms[:] = 1
    e.attacks[(e.times >= .74) & (e.times < .78), 39] = .9
    assert LocalRepair(lambda _: e)(notes, issue) == notes


def test_wrong_voice_and_missing_notes_do_not_invent_repairs():
    notes = (NoteEvent("a", .1, .7, 60, .8, 80),)
    def forbidden(_):
        raise AssertionError("No model work required")
    for kind in ("wrong_voice", "missing_notes"):
        assert LocalRepair(forbidden)(notes, (ReviewIssue(0, 1, kind, "改变声部"),)) == notes


def test_octave_bass_does_not_replace_instrumental_lead():
    notes = tuple(NoteEvent(str(i), i * .5, i * .5 + .4, 72, .4, 80) for i in range(3))
    e = evidence()
    assert LocalRepair(lambda _: e)(notes, (ReviewIssue(.5, .9, "octave", "八度"),)) == notes
