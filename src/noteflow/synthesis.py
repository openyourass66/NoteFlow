"""Render a MIDI snapshot with a local FluidSynth and SoundFont."""

import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from .errors import NoteFlowError
from .export import write_midi
from .process import check_cancelled, run_tool
from .score import Score


def _chunks(stream, end):
    while stream.tell() + 8 <= end:
        name, size = struct.unpack("<4sI", stream.read(8))
        stop = stream.tell() + size
        if stop > end:
            raise ValueError("Truncated SoundFont chunk")
        yield name, stop
        stream.seek(stop + (size & 1))


def _has_preset(path: Path, program: int) -> bool:
    with path.open("rb") as stream:
        header, size, form = struct.unpack("<4sI4s", stream.read(12))
        if (header, form) != (b"RIFF", b"sfbk") or size + 8 > path.stat().st_size:
            return False
        for name, stop in _chunks(stream, size + 8):
            if name != b"LIST" or stream.read(4) != b"pdta":
                continue
            for child, child_stop in _chunks(stream, stop):
                if child != b"phdr":
                    continue
                while stream.tell() + 76 <= child_stop:
                    _, preset, bank, *_ = struct.unpack("<20sHHHIII", stream.read(38))
                    if bank == 0 and preset == program:
                        return True
                return False
    return False


def render_preview(
    score: Score, program: int, soundfont: Path, target: Path, fluidsynth: str,
    cancel: Event, *, original_timing: bool = True,
) -> Path:
    check_cancelled(cancel)
    try:
        available = _has_preset(soundfont, program)
    except (OSError, ValueError, struct.error):
        available = False
    if not available:
        raise NoteFlowError("SYNTH_FAILED", "render", "音源缺失或没有此乐器预设，请在工具设置中选择 GM SoundFont。")

    try:
        with TemporaryDirectory(prefix="midi-", dir=target.parent) as directory:
            midi_path = Path(directory) / "preview.mid"
            write_midi(score, program, midi_path, original_timing=original_timing)
            run_tool(fluidsynth, "render", 90, (
                "-ni", "-r", "44100", "-T", "wav", "-F", str(target), str(soundfont), str(midi_path),
            ), cancel)
        with wave.open(str(target), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (44100, 2, 2):
                raise ValueError("Unexpected preview format")
            while block := audio.readframes(32768):
                check_cancelled(cancel)
                if any(block):
                    return target
        raise ValueError("Silent preview")
    except (OSError, ValueError, wave.Error, EOFError) as exc:
        raise NoteFlowError("SYNTH_FAILED", "render", "无法生成有效试听音频，请检查音源和 FluidSynth。") from exc
