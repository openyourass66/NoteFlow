"""Explicit musical intent, independent of the inference backend."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisOptions:
    target: str = "instrument"
    pitch_min: int = 36
    pitch_max: int = 96
    source: str = "auto"

    def __post_init__(self):
        if self.target not in ("instrument", "vocal"):
            raise ValueError("请选择乐器或人声主旋律。")
        if self.source not in ("auto", "original", "separated"):
            raise ValueError("请选择原曲或分离音轨。")
        if (type(self.pitch_min) is not int or type(self.pitch_max) is not int
                or not 21 <= self.pitch_min < self.pitch_max <= 108):
            raise ValueError("音域须在 MIDI 21–108 内，最低音应小于最高音。")


@dataclass(frozen=True, slots=True)
class UncertainRegion:
    start_s: float
    end_s: float
    reason: str
