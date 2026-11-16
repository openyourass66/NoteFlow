import json
from dataclasses import replace
from threading import Event

import pytest

from noteflow.errors import NoteFlowError
from noteflow.notes import NoteEvent
from noteflow.review import ReviewIssue, ReviewLimits, Verdict, parse_verdict, run_review, save_report


BASE = (NoteEvent("lead", .1, 1.0, 62, .7, 80),)
FIXED = (replace(BASE[0], midi=60),)
ISSUE = ReviewIssue(.1, 1.0, "pitch", "演奏偏高")


class Judge:
    def __init__(self, verdicts, preferences=()):
        self.verdicts, self.preferences = iter(verdicts), iter(preferences)
        self.comparisons = []

    def assess(self, notes, first, last):
        value = next(self.verdicts)
        if isinstance(value, Exception):
            raise value
        return value

    def compare(self, a, b, first, last):
        self.comparisons.append((a, b))
        return next(self.preferences), "听辨理由"


def test_repair_requires_both_orders_and_new_complete_assessment(tmp_path):
    judge = Judge([Verdict("issues", (ISSUE,)), Verdict("pass")], ["B", "A"])
    snapshots = []
    result = run_review(BASE, 2, judge, lambda *a: FIXED, checkpoint=snapshots.append)
    assert result.status == "passed" and result.notes == FIXED and result.baseline == BASE
    assert result.calls == 4 and result.accepted == 1
    assert judge.comparisons == [(BASE, FIXED), (FIXED, BASE)]
    assert snapshots[0].status != "passed"
    save_report(result, tmp_path / "report.json", model="test")
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved["accuracy"] is None and saved["baseline"][0]["midi"] == 62


@pytest.mark.parametrize("preferences", [("B", "B"), ("A",), ("tie",), ("uncertain",)])
def test_unreliable_comparison_preserves_baseline(preferences):
    result = run_review(BASE, 2, Judge([Verdict("issues", (ISSUE,))], preferences), lambda *a: FIXED)
    assert result.status == "no_improvement" and result.notes == BASE and not result.accepted


def test_every_window_must_pass_and_call_cap_cannot_be_reported_as_pass():
    judge = Judge([Verdict("pass")])
    result = run_review(BASE, 40, judge, lambda *a: FIXED, limits=ReviewLimits(max_calls=1))
    assert result.status == "call_limit" and result.calls == 1


def test_budget_before_second_order_cannot_commit_candidate():
    judge = Judge([Verdict("issues", (ISSUE,))], ["B"])
    result = run_review(BASE, 2, judge, lambda *a: FIXED, limits=ReviewLimits(max_calls=2))
    assert result.status == "call_limit" and result.notes == BASE


@pytest.mark.parametrize("failure,status", [(Verdict("uncertain"), "uncertain"),
    (NoteFlowError("REVIEW_HTTP", "review", "接口失败"), "error")])
def test_best_survives_later_uncertainty_or_network_failure(failure, status):
    judge = Judge([Verdict("issues", (ISSUE,)), failure], ["B", "A"])
    result = run_review(BASE, 2, judge, lambda *a: FIXED)
    assert result.status == status and result.notes == FIXED


def test_cancel_after_checkpoint_returns_accepted_version():
    flag = Event()
    judge = Judge([Verdict("issues", (ISSUE,))], ["B", "A"])
    def checkpoint(snapshot):
        if snapshot.accepted:
            flag.set()
    result = run_review(BASE, 2, judge, lambda *a: FIXED, cancel=flag, checkpoint=checkpoint)
    assert result.status == "cancelled" and result.notes == FIXED and result.calls == 3


def test_round_limit_is_not_a_pass():
    judge = Judge([Verdict("issues", (ISSUE,))], ["B", "A"])
    result = run_review(BASE, 2, judge, lambda *a: FIXED, limits=ReviewLimits(max_rounds=1))
    assert result.status == "round_limit" and result.notes == FIXED


def test_candidate_cannot_touch_unselected_or_cross_boundary_notes():
    judge = Judge([Verdict("issues", (ISSUE,))])
    result = run_review(BASE, 2, judge, lambda *a: FIXED, start_s=.5, end_s=1.5)
    assert result.status == "error" and result.notes == BASE and not judge.comparisons


def test_no_evidence_stops_without_paid_comparisons():
    judge = Judge([Verdict("issues", (ISSUE,))])
    result = run_review(BASE, 2, judge, lambda *a: BASE)
    assert result.status == "unsupported" and result.calls == 1


def test_cycle_detection_preserves_last_accepted_version():
    judge = Judge([Verdict("issues", (ISSUE,))] * 2, ["B", "A"])
    result = run_review(BASE, 2, judge, lambda notes, *_: FIXED if notes == BASE else BASE)
    assert result.status == "cycle" and result.notes == FIXED


@pytest.mark.parametrize("data", [
    {"status": "pass", "summary": "", "issues": [{"start_s": 0, "end_s": 1, "kind": "pitch", "explanation": "错"}]},
    {"status": "issues", "summary": "", "issues": []},
    {"status": "issues", "summary": "", "issues": [{"start_s": 4, "end_s": 6, "kind": "pitch", "explanation": "错"}]},
    {"status": "issues", "summary": "", "issues": [{"start_s": True, "end_s": 1, "kind": "pitch", "explanation": "错"}]},
    {"status": "issues", "summary": "", "issues": [{"start_s": 0, "end_s": float("nan"), "kind": "pitch", "explanation": "错"}]},
    {"status": "pass", "summary": "", "issues": [], "accuracy": 100},
])
def test_invalid_or_hallucinated_feedback_is_rejected(data):
    with pytest.raises(NoteFlowError):
        parse_verdict(json.dumps(data), 20, 25)


def test_local_timestamps_translate_exactly_once():
    verdict = parse_verdict(json.dumps({"status": "issues", "summary": "", "issues": [
        {"start_s": .5, "end_s": 1, "kind": "rhythm", "explanation": "晚起音"}]}), 20, 25)
    assert verdict.issues[0].start_s == 20.5


def test_uncertain_feedback_can_keep_proposals_but_never_auto_apply_them():
    judge = Judge([Verdict("uncertain", (ISSUE,))])
    result = run_review(BASE, 2, judge, lambda *a: FIXED)
    assert result.status == "uncertain" and result.notes == BASE and not judge.comparisons
    assert result.candidates[0].notes == FIXED
