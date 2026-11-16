import json
from dataclasses import asdict, replace

import pytest

from noteflow.notes import NoteEvent
from noteflow.review import (RepairCandidate, RepairPlan, ReviewIssue, ReviewLimits,
                             Verdict, fingerprint, run_review, save_report)
from noteflow.review_edit import apply_manual, candidate_notes, latest_issues, load_report


BASE = (NoteEvent("lead", .1, 1, 62, .7, 80), NoteEvent("later", 1.2, 1.8, 64, .8, 80))
FIXED = (replace(BASE[0], midi=60), BASE[1])
ISSUE = ReviewIssue(.1, 1, "pitch", "音高疑点")
CANDIDATE = RepairCandidate(FIXED, fingerprint(BASE), .1, 1, "局部重建")


def rejected_result(*, uncertain=False, limits=ReviewLimits()):
    class Reviewer:
        def assess(self, *_):
            return Verdict("uncertain" if uncertain else "issues", (ISSUE,), "需试听")
        def compare(self, *_):
            return "tie", "无法听出差别"
    class Repair:
        def propose(self, *_):
            return RepairPlan((CANDIDATE,), ({"start_s": .1, "end_s": 1, "summary": "已重建"},))
    return run_review(BASE, 2, Reviewer(), Repair(), limits=limits)


@pytest.mark.parametrize("uncertain,limits,status", [
    (False, ReviewLimits(), "no_improvement"), (True, ReviewLimits(), "uncertain"),
    (False, ReviewLimits(max_calls=1), "call_limit"),
])
def test_unaccepted_candidates_remain_auditionable_and_manually_applicable(uncertain, limits, status):
    result = rejected_result(uncertain=uncertain, limits=limits)
    assert result.status == status and result.notes == BASE
    assert result.candidates == (CANDIDATE,)
    assert latest_issues(result) == (ISSUE,)
    updated = apply_manual(result, CANDIDATE, BASE, 2)
    assert updated.notes == FIXED and updated.status == "manual"
    assert updated.accepted == 0 and updated.calls == result.calls and not updated.candidates
    assert updated.events[-1]["stage"] == "manual" and updated.events[-1]["changes"]


def test_manual_apply_rejects_stale_or_out_of_region_edits():
    with pytest.raises(ValueError, match="乐谱已变化"):
        candidate_notes(CANDIDATE, FIXED, 2)
    bad = replace(CANDIDATE, notes=(FIXED[0], replace(BASE[1], midi=70)))
    with pytest.raises(ValueError, match="越过"):
        candidate_notes(bad, BASE, 2)
    assert fingerprint(BASE) == fingerprint(tuple(replace(n, id=n.id + "new", strength=.9) for n in BASE))


@pytest.mark.parametrize("version", [1, 2])
def test_import_old_and_new_feedback_regenerates_candidates_and_keeps_usage(tmp_path, version):
    source, destination = tmp_path / "saved.json", tmp_path / "exported.json"
    save_report(replace(rejected_result(), model="audio-model", usage={"total_tokens": 100}), source)
    data = json.loads(source.read_text(encoding="utf-8"))
    data["version"] = version
    data["candidates"] = [{"notes": [{"midi": 100}]}]
    source.write_text(json.dumps(data), encoding="utf-8")
    result = load_report(source, BASE, 2)
    assert latest_issues(result) == (ISSUE,) and not result.candidates
    save_report(result, destination)
    copied = json.loads(destination.read_text(encoding="utf-8"))
    assert copied["model"] == "audio-model" and copied["usage"]["total_tokens"] == 100
    assert "candidates" in json.loads(source.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="不匹配"):
        load_report(source, FIXED, 2)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(end_s=3),
    lambda d: d["events"].append({"stage": "repair", "round": 1}),
    lambda d: d["events"][0].update(issues=None),
    lambda d: d["events"][0].update(status="pass"),
    lambda d: d["notes"][0].update(start_s=float("nan")),
])
def test_malformed_import_cannot_change_score_or_crash_result_window(tmp_path, mutation):
    path = tmp_path / "bad.json"
    data = {"version": 2, **asdict(rejected_result())}
    data = json.loads(json.dumps(data))
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_report(path, BASE, 2)


def test_report_import_tolerates_sample_rate_rounding_at_media_end(tmp_path):
    path = tmp_path / "saved.json"
    result = rejected_result()
    assessment = {**result.events[0], "end_s": 2.00002, "issues": [
        {"start_s": 1.9, "end_s": 2.00002, "kind": "rhythm", "explanation": "尾音"}]}
    save_report(replace(result, end_s=2.00002, events=(assessment,)), path)
    loaded = load_report(path, BASE, 2)
    assert loaded.end_s == 2 and latest_issues(loaded)[0].end_s == 2
