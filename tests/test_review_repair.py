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


def test_phrase_rebuild_can_repair_large_pitch_errors_and_missing_notes():
    from noteflow.review_edit import candidate_notes
    e = evidence()
    notes = (NoteEvent("a", .1, .7, 65, .4, 80), NoteEvent("b", 1.4, 1.8, 60, .8, 80))
    repair = LocalRepair(lambda _: e, end_s=2)
    plan = repair.propose(notes, (ReviewIssue(.1, .7, "pitch", "需重新判断音高"),))
    assert plan.candidates and plan.candidates[0].notes[0].midi == 60
    assert plan.candidates[0].notes[1] == notes[1]
    assert candidate_notes(plan.candidates[0], notes, 2)
    missing = repair.propose(notes, (ReviewIssue(.8, 1.2, "missing_notes", "缺少音符"),))
    assert len(missing.candidates[0].notes) == 3
    assert missing.candidates[0].notes[0] == notes[0] and missing.candidates[0].notes[-1] == notes[-1]


def test_rebuild_uses_audio_timing_and_preserves_real_silence():
    e = evidence()
    quiet = (e.times >= .7) & (e.times < .95)
    e.frames[quiet] = 0
    e.rms[quiet] = 0
    notes = (NoteEvent("a", .1, 1.5, 60, .8, 80),)
    plan = LocalRepair(lambda _: e, end_s=2).propose(notes, (ReviewIssue(0, 1.5, "rhythm", "整段晚了3秒"),))
    rebuilt = plan.candidates[-1].notes
    assert len(rebuilt) == 2
    assert rebuilt[0].start_s < .1 and rebuilt[0].end_s <= .71
    assert rebuilt[1].start_s >= .94 and rebuilt[1].end_s <= 1.5


def test_phrase_cannot_rewrite_notes_crossing_selected_boundary():
    from noteflow.review_edit import candidate_notes
    e = evidence()
    notes = (NoteEvent("cross", .1, .7, 65, .8, 80), NoteEvent("in", .8, 1.5, 65, .8, 80))
    plan = LocalRepair(lambda _: e, start_s=.4, end_s=1.7).propose(notes, (ReviewIssue(.4, 1.7, "pitch", "音高"),))
    assert plan.candidates
    for candidate in plan.candidates:
        assert candidate.notes[0] == notes[0]
        candidate_notes(candidate, notes, 2)


def test_phrase_rebuild_preserves_acoustically_supported_repeated_attack():
    e = evidence()
    e.onsets[80, 60 - 21] = .95
    e.attacks[80, 60 - 21] = .95
    notes = (NoteEvent("a", .1, 1.5, 60, .8, 80),)
    plan = LocalRepair(lambda _: e, end_s=2).propose(notes, (ReviewIssue(.1, 1.5, "fragmentation", "连贯性"),))
    assert len(plan.candidates[-1].notes) == 2
    assert abs(plan.candidates[-1].notes[1].start_s - .8) < .02
