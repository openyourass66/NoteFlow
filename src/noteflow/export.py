"""Serialize the same score for MIDI playback and user exports."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import mido

from .score import BAR, KEYS, PPQ, Score, to_text

AUTO_INSTRUMENT = "自动"
GUZHENG_PROGRAM = 107
PROGRAMS = {
    "钢琴": 0, "电钢琴": 4, "羽管键琴": 6, "钟琴": 9, "颤音琴": 11, "马林巴": 12,
    "木琴": 13, "风琴": 19, "手风琴": 21, "尼龙吉他": 24, "钢弦吉他": 25,
    "清音电吉他": 27, "原声贝斯": 32, "电贝斯": 33, "小提琴": 40, "中提琴": 41,
    "大提琴": 42, "竖琴": 46, "弦乐合奏": 48, "人声哼唱": 53, "小号": 56,
    "长号": 57, "圆号": 60, "中音萨克斯": 65, "双簧管": 68, "单簧管": 71, "长笛": 73,
    "古筝": GUZHENG_PROGRAM,
}
PROGRAM_NAMES = {program: name for name, program in PROGRAMS.items()}


def write_midi(score: Score, program: int, path: Path, *, original_timing: bool = True) -> None:
    midi = mido.MidiFile(type=0, ticks_per_beat=PPQ)
    track = midi.add_track()
    track.append(mido.MetaMessage("set_tempo", tempo=score.settings.tempo_us))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    track.append(mido.MetaMessage("key_signature", key=KEYS[score.settings.tonic_pc]))
    track.append(mido.Message("program_change", channel=0, program=program))
    if original_timing:
        tempo = score.settings.tempo_us
        notes = ((mido.second2tick(note.start_s, PPQ, tempo),
                  mido.second2tick(note.end_s, PPQ, tempo), note.midi, note.velocity)
                 for note in score.melody)
    else:
        notes = ((note.start_tick, note.start_tick + note.duration_tick, note.midi, note.velocity)
                 for note in score.grid.notes)

    events = []
    for start, end, pitch, velocity in notes:
        start, end = round(start), round(end)
        events.append((start, 1, pitch, velocity))
        events.append((max(start + 1, end), 0, pitch, 0))
    previous = 0
    for tick, on, pitch, velocity in sorted(events):
        track.append(mido.Message("note_on" if on else "note_off", channel=0,
                                  note=pitch, velocity=velocity, time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0 if original_timing else len(score.measures) * BAR - previous))
    midi.save(path)


def export_score(score: Score, program: int, path: Path, *, midi: bool, overwrite: bool) -> None:
    with NamedTemporaryFile(dir=path.parent, prefix=".noteflow-", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        if midi:
            write_midi(score, program, temporary)
        else:
            temporary.write_text(to_text(score), encoding="utf-8", newline="\n")
        if overwrite:
            os.replace(temporary, path)
        elif os.name == "nt":
            os.rename(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
