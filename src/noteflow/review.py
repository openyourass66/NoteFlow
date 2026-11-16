"""Bounded audio review with immutable snapshots and conservative acceptance."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import NoteFlowError
from .notes import NoteEvent
from .process import Cancelled, check_cancelled


KINDS = {"pitch", "octave", "rhythm", "fragmentation", "wrong_voice", "missing_notes"}


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    start_s: float
    end_s: float
    kind: str
    explanation: str


@dataclass(frozen=True, slots=True)
class Verdict:
    status: str  # pass, issues, uncertain
    issues: tuple[ReviewIssue, ...] = ()
    summary: str = ""


@dataclass(frozen=True, slots=True)
class ReviewLimits:
    max_rounds: int = 3
    max_calls: int = 24
    window_s: float = 20.0

    def __post_init__(self):
        if (type(self.max_rounds) is not int or not 1 <= self.max_rounds <= 3
                or type(self.max_calls) is not int or not 1 <= self.max_calls <= 60
                or not math.isfinite(self.window_s) or not 5 <= self.window_s <= 20):
            raise ValueError("复核上限无效。")


@dataclass(frozen=True, slots=True)
class ReviewResult:
    baseline: tuple[NoteEvent, ...]
    notes: tuple[NoteEvent, ...]
    status: str
    calls: int
    rounds: int
    accepted: int
    events: tuple[dict, ...]
    start_s: float
    end_s: float


STATUS_TEXT = {
    "passed": "所选范围的云端复核通过，仍请试听确认",
    "uncertain": "云端无法可靠判断，已停止",
    "unsupported": "本地证据不足或需要手动选择声部，已停止",
    "no_improvement": "前后对照没有一致支持改进，已保留上一版本",
    "round_limit": "达到轮数上限，尚未通过最终复核",
    "call_limit": "达到调用上限，尚未完成全部复核",
    "cycle": "候选重复，已停止循环",
    "cancelled": "复核已取消，已保留上一次采用的版本",
    "error": "复核中断，已保留上一次采用的版本",
}


def fingerprint(notes):
    payload = [(n.id, n.start_s, n.end_s, n.midi, n.velocity, n.strength) for n in notes]
    return hashlib.sha256(json.dumps(payload, allow_nan=False).encode()).hexdigest()


def validate_notes(notes, duration):
    previous, ids = 0.0, set()
    for note in notes:
        if (not isinstance(note, NoteEvent) or note.id in ids or not note.id
                or not all(math.isfinite(v) for v in (note.start_s, note.end_s))
                or not 0 <= note.start_s < note.end_s <= duration + 1e-5
                or note.start_s < previous - 1e-5
                or type(note.midi) is not int or not 0 <= note.midi <= 127
                or type(note.velocity) is not int or not 1 <= note.velocity <= 127
                or (note.strength is not None and not 0 <= note.strength <= 1)):
            raise ValueError("复核音符必须有效、有序且互不重叠。")
        ids.add(note.id)
        previous = note.end_s


def parse_verdict(text: str, start: float, end: float) -> Verdict:
    """Only accept a complete response with valid, clip-relative timestamps."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or set(data) != {"status", "summary", "issues"}:
            raise ValueError
        status, summary, entries = data["status"], data["summary"], data["issues"]
        if (status not in ("pass", "issues", "uncertain") or not isinstance(summary, str)
                or len(summary) > 2000 or not isinstance(entries, list) or len(entries) > 12):
            raise ValueError
        issues = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"start_s", "end_s", "kind", "explanation"}:
                raise ValueError
            first, last = entry["start_s"], entry["end_s"]
            if (type(first) not in (int, float) or type(last) not in (int, float)
                    or not math.isfinite(first) or not math.isfinite(last)
                    or not 0 <= first < last <= end - start + 1e-5
                    or entry["kind"] not in KINDS or not isinstance(entry["explanation"], str)
                    or not 1 <= len(entry["explanation"]) <= 1000):
                raise ValueError
            issues.append(ReviewIssue(start + first, start + last, entry["kind"], entry["explanation"]))
        if (status == "pass" and issues) or (status == "issues" and not issues):
            raise ValueError
        return Verdict(status, tuple(issues), summary)
    except (ValueError, TypeError, KeyError) as exc:
        raise NoteFlowError("REVIEW_RESPONSE", "review", "云端回复格式或时间范围无效，本次回复未用于修改。") from exc


def parse_preference(text: str) -> tuple[str, str]:
    try:
        data = json.loads(text)
        if (not isinstance(data, dict) or set(data) != {"preference", "summary"}
                or data["preference"] not in ("A", "B", "tie", "uncertain")
                or not isinstance(data["summary"], str) or len(data["summary"]) > 2000):
            raise ValueError
        return data["preference"], data["summary"]
    except (ValueError, TypeError, KeyError) as exc:
        raise NoteFlowError("REVIEW_RESPONSE", "review", "云端对照回复无效，未采用候选修改。") from exc


class _CallLimit(Exception):
    pass


def run_review(notes, duration, reviewer, repair, *, start_s=0.0, end_s=None,
               limits=ReviewLimits(), cancel=None, progress=None, checkpoint=None):
    """Reviewer handles audio; repair proposes notes using local evidence only.

    Every request is charged against the call limit, including failed requests.
    A candidate must win both A/B orders for EVERY changed window before commit.
    """
    end_s = duration if end_s is None else end_s
    if not all(map(math.isfinite, (duration, start_s, end_s))) or not 0 <= start_s < end_s <= duration:
        raise ValueError("请选择音轨内有效的复核范围。")
    notes = tuple(notes)
    validate_notes(notes, duration)
    baseline = best = notes
    seen, events = {fingerprint(notes)}, []
    calls = rounds = accepted = 0
    windows, cursor = [], start_s
    while cursor < end_s - 1e-5:
        stop = min(end_s, cursor + limits.window_s)
        windows.append((cursor, stop))
        cursor = stop

    def result(status):
        snapshot = ReviewResult(baseline, best, status, calls, rounds, accepted, tuple(events), start_s, end_s)
        if checkpoint:
            checkpoint(snapshot)
        return snapshot

    def call(operation, *args):
        nonlocal calls
        check_cancelled(cancel)
        if calls >= limits.max_calls:
            raise _CallLimit
        calls += 1
        if progress:
            progress(f"音频复核 · 第 {rounds}/{limits.max_rounds} 轮 · 请求 {calls}/{limits.max_calls}")
        value = operation(*args)
        check_cancelled(cancel)
        return value

    try:
        for rounds in range(1, limits.max_rounds + 1):
            issues, uncertain = [], False
            for first, last in windows:
                verdict = call(reviewer.assess, best, first, last)
                events.append({"round": rounds, "stage": "assess", "start_s": first, "end_s": last,
                               **asdict(verdict)})
                issues.extend(verdict.issues)
                uncertain |= verdict.status == "uncertain"
            if uncertain:
                return result("uncertain")
            if not issues:
                return result("passed")
            check_cancelled(cancel)
            if progress:
                progress("正在用本地音高与起音证据检查疑点…")
            candidate = tuple(repair(best, tuple(issues), cancel))
            validate_notes(candidate, duration)
            # Local edits cannot affect any note crossing the review boundary.
            outside = lambda ns: tuple(n for n in ns if n.start_s < start_s or n.end_s > end_s)
            if outside(candidate) != outside(best):
                raise ValueError("候选修改超出所选复核范围。")
            signature = fingerprint(candidate)
            if candidate == best:
                return result("unsupported")
            if signature in seen:
                return result("cycle")
            seen.add(signature)
            changed_windows = [(first, last) for first, last in windows
                               if tuple(n for n in best if n.end_s > first and n.start_s < last)
                               != tuple(n for n in candidate if n.end_s > first and n.start_s < last)]
            for first, last in changed_windows:
                for reverse in (False, True):
                    a, b = (candidate, best) if reverse else (best, candidate)
                    choice, summary = call(reviewer.compare, a, b, first, last)
                    expected = "A" if reverse else "B"
                    events.append({"round": rounds, "stage": "compare", "start_s": first, "end_s": last,
                                   "reversed": reverse, "preference": choice, "summary": summary})
                    if choice != expected:
                        return result("no_improvement")
            check_cancelled(cancel)
            best, accepted = candidate, accepted + 1
            events.append({"round": rounds, "stage": "accepted", "fingerprint": signature})
            result("round_limit")  # Durable checkpoint of an accepted version, not a pass.
        return result("round_limit")
    except _CallLimit:
        return result("call_limit")
    except Cancelled:
        return result("cancelled")
    except (NoteFlowError, ValueError, OSError) as error:
        events.append({"round": rounds, "stage": "error",
                       "code": getattr(error, "code", "REVIEW_LOCAL"),
                       "summary": str(error) if isinstance(error, NoteFlowError) else "本地复核处理失败。"})
        return result("error")


def save_report(result: ReviewResult, destination: Path, *, model="", usage=None):
    payload = {"version": 1, "model": model, "accuracy": None, "usage": usage or {}, **asdict(result)}
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(destination)
