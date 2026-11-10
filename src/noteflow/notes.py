from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NoteEvent:
    id: str
    start_s: float
    end_s: float
    midi: int
    strength: float | None
    velocity: int
