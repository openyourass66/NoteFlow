"""Quantize a melody and map it to four-beat numbered notation."""

import math
from dataclasses import dataclass, replace
from fractions import Fraction
from heapq import heappop, heappush

from .notes import NoteEvent

PPQ = 480
GRID = 120
BAR = 4 * PPQ
BPM_MIN, BPM_MAX = 40, 240
KEYS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
PITCHES = ((1, ""), (1, "♯"), (2, ""), (3, "♭"), (3, ""), (4, ""),
           (4, "♯"), (5, ""), (6, "♭"), (6, ""), (7, "♭"), (7, ""))
DURATIONS = (BAR, 960, PPQ, 240, GRID)


@dataclass(frozen=True, slots=True)
class ScoreSettings:
    bpm: float = 120
    first_beat_s: float = 0
    tonic_pc: int = 0

    def __post_init__(self):
        if not BPM_MIN <= self.bpm <= BPM_MAX:
            raise ValueError("BPM 必须在 40 至 240 之间。")
        if not 0 <= self.first_beat_s < self.tempo_us / 1_000_000:
            raise ValueError("首拍偏移必须小于一拍。")
        if type(self.tonic_pc) is not int or not 0 <= self.tonic_pc < len(KEYS):
            raise ValueError("请选择有效的主音。")

    @property
    def tempo_us(self) -> int:
        return round(60_000_000 / self.bpm)


@dataclass(frozen=True, slots=True)
class QuantizedNote:
    id: str
    start_tick: int
    duration_tick: int
    midi: int
    velocity: int


@dataclass(frozen=True, slots=True)
class BeatGrid:
    notes: tuple[QuantizedNote, ...]
    shift_ticks: int
    overlap_drops: int
    merged: int
    clipped: int


@dataclass(frozen=True, slots=True)
class JianpuToken:
    note_id: str | None
    degree: int
    accidental: str
    octave: int
    duration_tick: int
    tie_out: bool = False


@dataclass(frozen=True, slots=True)
class Score:
    settings: ScoreSettings
    grid: BeatGrid
    measures: tuple[tuple[JianpuToken, ...], ...]
    revision: int
    melody: tuple[NoteEvent, ...]


def _strength(note: NoteEvent) -> float:
    return 0.5 if note.strength is None else note.strength


def monophonic(notes: tuple[NoteEvent, ...]) -> tuple[NoteEvent, ...]:
    """Find a continuous melody through the candidate notes."""
    candidates = sorted(notes, key=lambda note: (note.start_s, -_strength(note), -note.end_s, note.midi))
    scores = [0.0]  # Index 0 is the empty path.
    predecessors = [0]
    recent: list[tuple[float, int]] = []
    best_distant = best = 0
    continuity_s = 0.6
    for index, note in enumerate(candidates, start=1):
        while recent and recent[0][0] <= note.start_s - continuity_s:
            _, previous_index = heappop(recent)
            if scores[previous_index] > scores[best_distant]:
                best_distant = previous_index

        # A sustained accompaniment note should not outweigh an entire phrase.
        support = (0.5 + _strength(note)) * min(0.5, note.end_s - note.start_s)
        previous_best, score = best_distant, scores[best_distant] + support
        for end, previous_index in recent:
            previous = candidates[previous_index - 1]
            gap = note.start_s - end
            # Let a new attack cut a short release tail, but require distinct attacks.
            tail = min(0.085, (end - previous.start_s) / 3)
            if note.start_s <= previous.start_s or gap < -tail:
                continue
            distance = min(12, abs(note.midi - previous.midi)) / 12
            proximity = 1 - max(0, gap) / continuity_s
            leap_cost = 0.55 * min(support, end - previous.start_s) * distance * proximity
            value = scores[previous_index] + support - leap_cost + min(0, gap)
            if value > score:
                previous_best, score = previous_index, value

        scores.append(score)
        predecessors.append(previous_best)
        heappush(recent, (note.end_s, index))
        if score > scores[best]:
            best = index

    selected = []
    while best:
        note = candidates[best - 1]
        if selected and note.end_s > selected[-1].start_s:
            note = replace(note, end_s=selected[-1].start_s)
        selected.append(note)
        best = predecessors[best]
    return tuple(reversed(selected))


def _quantize(selected: tuple[NoteEvent, ...], settings: ScoreSettings, overlap_drops: int) -> BeatGrid:
    tick_per_second = PPQ * 1_000_000 / settings.tempo_us

    def tick(seconds: float) -> int:
        return math.floor((seconds - settings.first_beat_s) * tick_per_second / GRID + 0.5) * GRID

    by_start: dict[int, NoteEvent] = {}
    for note in selected:
        start = tick(note.start_s)
        if start not in by_start or _strength(note) > _strength(by_start[start]):
            by_start[start] = note

    entries = list(by_start.items())
    first = entries[0][0] if entries else 0
    shift = max(0, (-first + BAR - 1) // BAR) * BAR
    quantized = []
    clipped = 0
    for index, (start, note) in enumerate(entries):
        end = max(start + GRID, tick(note.end_s))
        if index + 1 < len(entries) and end > entries[index + 1][0]:
            end = entries[index + 1][0]
            clipped += 1
        quantized.append(QuantizedNote(note.id, start + shift, end - start, note.midi, note.velocity))
    return BeatGrid(tuple(quantized), shift, overlap_drops, len(selected) - len(entries), clipped)


def _measures(grid: BeatGrid, tonic: int) -> tuple[tuple[JianpuToken, ...], ...]:
    measures: list[list[JianpuToken]] = [[]]
    cursor = 0

    def append(end: int, note: QuantizedNote | None = None) -> None:
        nonlocal cursor
        octave, pitch = divmod(note.midi - 60 - tonic, 12) if note else (0, 0)
        degree, accidental = PITCHES[pitch] if note else (0, "")
        while cursor < end:
            if cursor and cursor % BAR == 0:
                measures.append([])
            available = min(end - cursor, BAR - cursor % BAR)
            for duration in DURATIONS:
                while available >= duration:
                    available -= duration
                    cursor += duration
                    measures[-1].append(JianpuToken(
                        note.id if note else None, degree, accidental, octave, duration, note is not None and cursor < end,
                    ))

    for note in grid.notes:
        append(note.start_tick)
        append(note.start_tick + note.duration_tick, note)
    append(max(BAR, ((cursor + BAR - 1) // BAR) * BAR))
    return tuple(tuple(measure) for measure in measures)


def build_score(notes: tuple[NoteEvent, ...], settings: ScoreSettings, revision: int = 0) -> Score:
    melody = monophonic(notes)
    grid = _quantize(melody, settings, len(notes) - len(melody))
    return Score(settings, grid, _measures(grid, settings.tonic_pc), revision, melody)


def rekey(score: Score, tonic: int, revision: int) -> Score:
    settings = replace(score.settings, tonic_pc=tonic)
    return replace(score, settings=settings, measures=_measures(score.grid, tonic), revision=revision)


def to_text(score: Score) -> str:
    def token_text(token: JianpuToken) -> str:
        octave = "^" * token.octave if token.octave > 0 else "v" * -token.octave
        duration = Fraction(token.duration_tick, PPQ)
        return f"{token.accidental}{token.degree}{octave}[{duration}]" + ("~" if token.tie_out else "")

    settings = score.settings
    header = f"1={KEYS[settings.tonic_pc]}  4/4  BPM={settings.bpm:g}"
    bars = [" ".join(map(token_text, measure)) for measure in score.measures]
    rows = [" | ".join(bars[index:index + 4]) for index in range(0, len(bars), 4)]
    return header + "\n" + " |\n".join(rows) + "\n"
