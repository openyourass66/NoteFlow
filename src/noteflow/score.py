"""Quantize a melody and map it to four-beat numbered notation."""

import math
from bisect import bisect_left
from dataclasses import dataclass, replace
from fractions import Fraction

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


def _strength(note: NoteEvent) -> float:
    return 0.5 if note.strength is None else note.strength


def monophonic(notes: tuple[NoteEvent, ...]) -> tuple[NoteEvent, ...]:
    ranked = sorted(enumerate(notes), key=lambda pair: (
        -_strength(pair[1]), pair[1].start_s, pair[1].start_s - pair[1].end_s, pair[1].midi, pair[0],
    ))
    accepted, starts = [], []
    for _, note in ranked:
        index = bisect_left(starts, note.start_s)
        if index and accepted[index - 1].end_s > note.start_s:
            continue
        if index < len(starts) and starts[index] < note.end_s:
            continue
        starts.insert(index, note.start_s)
        accepted.insert(index, note)
    return tuple(accepted)


def quantize(notes: tuple[NoteEvent, ...], settings: ScoreSettings) -> BeatGrid:
    selected = monophonic(notes)
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
    return BeatGrid(tuple(quantized), shift, len(notes) - len(selected), len(selected) - len(entries), clipped)


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
    grid = quantize(notes, settings)
    return Score(settings, grid, _measures(grid, settings.tonic_pc), revision)


def rekey(score: Score, tonic: int, revision: int) -> Score:
    settings = replace(score.settings, tonic_pc=tonic)
    return Score(settings, score.grid, _measures(score.grid, tonic), revision)


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
