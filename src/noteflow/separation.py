"""Split the first audio stream with an external Demucs environment."""

import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from .errors import NoteFlowError
from .media import MediaInfo, decode_original
from .process import check_cancelled, run_tool

MODEL = "htdemucs"
STEM_RATE = 44100


@dataclass(frozen=True, slots=True)
class Stems:
    vocals: Path
    accompaniment: Path


def separate(media: MediaInfo, destination: Path, *, python: str, ffmpeg: str = "ffmpeg",
             cancel: Event | None = None, device: str = "auto") -> Stems:
    """Publish both stems together into a new directory owned by the caller."""
    if not python:
        raise NoteFlowError("TOOL_NOT_FOUND", "separate", "请在工具设置中选择已安装 Demucs 的 Python。")
    destination = destination.resolve()
    with TemporaryDirectory(prefix="split-", dir=destination.parent) as directory:
        work = Path(directory)
        mix = decode_original(media, work / "mix.wav", ffmpeg, cancel, sample_rate=STEM_RATE)
        if device not in ("auto", "cpu", "cuda"):
            raise ValueError("Unknown device")
        if device == "auto":
            available = run_tool(python, "separate", 30,
                                 ("-I", "-c", "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')"), cancel)
            device = available.decode().strip()
        run_tool(python, "separate", 900, (
            "-I", "-m", "demucs.separate", "-n", MODEL, "-d", device, "--shifts", "0",
            "--two-stems", "vocals", "--filename", "{stem}.{ext}", "-o", str(work), str(mix),
        ), cancel)
        output = work / MODEL
        try:
            with wave.open(str(mix), "rb") as wav:
                frames = wav.getnframes()
            for name in ("vocals.wav", "no_vocals.wav"):
                with wave.open(str(output / name), "rb") as wav:
                    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) != (
                        2, 2, STEM_RATE, frames
                    ) or len(wav.readframes(frames)) != frames * 4:
                        raise ValueError("Incomplete or misaligned stem")
            check_cancelled(cancel)
            output.rename(destination)
        except (OSError, EOFError, ValueError, wave.Error) as exc:
            raise NoteFlowError("SEPARATION_FAILED", "separate", "分离结果不完整或音轨时长不一致，请重试。") from exc
    return Stems(destination / "vocals.wav", destination / "no_vocals.wav")
