"""Validated review snapshots shared by automatic and manual score editing."""

import json
import math
from dataclasses import replace
from pathlib import Path

from .notes import NoteEvent
from .review import (KINDS, STATUS_TEXT, ReviewIssue, ReviewResult,
                     fingerprint, save_report, validate_notes)


def latest_issues(result):
    assessments = [e for e in result.events if e["stage"] == "assess"]
    last_round = max((e["round"] for e in assessments), default=0)
    return tuple(ReviewIssue(**issue) for e in assessments if e["round"] == last_round for issue in e["issues"])


def note_changes(before, after):
    old, new = {n.id: n for n in before}, {n.id: n for n in after}
    changes = []
    for note in before:
        other = new.get(note.id)
        if other is None:
            changes.append(f"移除 {note.start_s:.3f}–{note.end_s:.3f} 秒的音符 {note.midi}")
        else:
            parts = []
            if note.midi != other.midi:
                parts.append(f"音高 {note.midi} → {other.midi}")
            if abs(note.start_s - other.start_s) > .001 or abs(note.end_s - other.end_s) > .001:
                parts.append(f"起止 {note.start_s:.3f}–{note.end_s:.3f} → {other.start_s:.3f}–{other.end_s:.3f} 秒")
            if parts:
                changes.append("；".join(parts))
    for note in after:
        if note.id not in old:
            changes.append(f"新增 {note.start_s:.3f}–{note.end_s:.3f} 秒的音符 {note.midi}")
    return changes


def candidate_notes(candidate, current, duration):
    if fingerprint(current) != candidate.baseline_fingerprint:
        raise ValueError("乐谱已变化，请根据当前乐谱重新生成候选，不能套用旧修改。")
    validate_notes(candidate.notes, duration)
    first, last = candidate.start_s, candidate.end_s
    if not math.isfinite(first) or not math.isfinite(last) or not 0 <= first < last <= duration + 1e-5:
        raise ValueError("候选范围无效。")
    outside = lambda notes: tuple(n for n in notes if n.start_s < first or n.end_s > last)
    if outside(candidate.notes) != outside(current):
        raise ValueError("候选修改越过了选定区域，未应用。")
    return candidate.notes


def apply_manual(result, candidate, current, duration):
    notes = candidate_notes(candidate, current, duration)
    event = {"round": result.rounds, "stage": "manual", "start_s": candidate.start_s,
             "end_s": candidate.end_s, "summary": f"手动应用：{candidate.title}",
             "changes": note_changes(current, notes)}
    return replace(result, notes=notes, status="manual", candidates=(), events=(*result.events, event))


def write_report(result, path, *, previous=None):
    """Keep provider usage when updating a report after a local action."""
    metadata = {}
    if previous and Path(previous).is_file():
        metadata = json.loads(Path(previous).read_text(encoding="utf-8-sig"))
    model = metadata.get("model", "")
    usage = metadata.get("usage", {})
    if not isinstance(model, str) or not isinstance(usage, dict):
        raise ValueError("复核记录元数据无效。")
    path.parent.mkdir(parents=True, exist_ok=True)
    save_report(result, path, model=model, usage=usage)


def load_report(path: Path, current, duration):
    """Import existing feedback without sending the user's music again."""
    try:
        if path.stat().st_size > 8_000_000:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data["version"] not in (1, 2) or data["status"] not in STATUS_TEXT:
            raise ValueError
        def notes(values):
            if not isinstance(values, list) or len(values) > 10000:
                raise ValueError
            parsed = tuple(NoteEvent(**n) for n in values)
            validate_notes(parsed, duration)
            return parsed
        original, current_report = notes(data["baseline"]), notes(data["notes"])
        if fingerprint(current_report) != fingerprint(current):
            raise ValueError("复核记录与当前音符不匹配，请打开对应项目后导入。")
        first, last = float(data["start_s"]), float(data["end_s"])
        # Saved projects can decode at another sample rate. A sub-millisecond
        # rounding difference at the media end must not reject matching notes.
        if not 0 <= first < last <= duration + .001:
            raise ValueError
        last = min(last, duration)
        for name, limit in (("calls", 60), ("rounds", 3), ("accepted", 3)):
            if type(data[name]) is not int or not 0 <= data[name] <= limit:
                raise ValueError
        events = data["events"]
        if not isinstance(events, list) or len(events) > 500:
            raise ValueError
        for event in events:
            if not isinstance(event, dict) or event.get("stage") not in {"assess", "compare", "accepted", "error", "repair", "manual"}:
                raise ValueError
            if type(event.get("round")) is not int or not 0 <= event["round"] <= 3:
                raise ValueError
            if "end_s" in event and last < event["end_s"] <= last + .001:
                event["end_s"] = last
            if event["stage"] in {"assess", "compare", "error", "repair", "manual"}:
                if not isinstance(event.get("summary"), str) or len(event["summary"]) > 10000:
                    raise ValueError
            if event["stage"] == "assess":
                if event["status"] not in ("pass", "issues", "uncertain") or not isinstance(event["summary"], str):
                    raise ValueError
                if (not first <= event["start_s"] < event["end_s"] <= last + 1e-5
                        or not isinstance(event["issues"], list) or len(event["issues"]) > 12):
                    raise ValueError
                if event["status"] == "pass" and event["issues"]:
                    raise ValueError
                for value in event["issues"]:
                    if last < value["end_s"] <= last + .001:
                        value["end_s"] = last
                    issue = ReviewIssue(**value)
                    if (not event["start_s"] <= issue.start_s < issue.end_s <= event["end_s"] + 1e-5
                            or issue.kind not in KINDS or not isinstance(issue.explanation, str)
                            or len(issue.explanation) > 10000):
                        raise ValueError
        # Imported proposals are regenerated from current local audio. This
        # avoids trusting arbitrary note patches in an external JSON document.
        return ReviewResult(original, tuple(current), data["status"], data["calls"], data["rounds"],
                            data["accepted"], tuple(events), first, last)
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, ValueError) and "不匹配" in str(error):
            raise
        raise ValueError("无法读取有效的复核记录，请选择对应乐谱导出的 JSON 文件。") from error
