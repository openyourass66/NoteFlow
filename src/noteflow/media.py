"""Probe local files and decode their first audio stream to PCM."""

import json
import math
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from .errors import NoteFlowError

SAMPLE_RATE = 22050
MAX_SECONDS = 120
MAX_BYTES = 200_000_000
FORMATS = {".wav": ("wav", "pcm_"), ".mp3": ("mp3", "mp3"), ".mp4": ("mov", "aac")}


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    stream_index: int
    codec: str


@dataclass(frozen=True, slots=True)
class AudioAsset:
    path: Path
    duration_s: float
    has_signal: bool


def _run_tool(command: str, stage: str, timeout: int, *args: str) -> bytes:
    executable = shutil.which(command)
    if executable is None:
        raise NoteFlowError("TOOL_NOT_FOUND", stage, "找不到媒体工具，请检查 FFmpeg 和 ffprobe 的路径。")
    try:
        result = subprocess.run(
            [str(Path(executable).resolve()), *args], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise NoteFlowError("DECODE_FAILED", stage, "媒体工具运行超时，请检查文件是否损坏。") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NoteFlowError("DECODE_FAILED", stage, "无法读取媒体，请检查文件格式或文件是否损坏。") from exc
    return result.stdout


def _check_duration(duration: float, stage: str) -> None:
    if duration > MAX_SECONDS:
        raise NoteFlowError("INPUT_LIMIT", stage, f"音轨超过 {MAX_SECONDS} 秒，请截取片段后重试。")


def _known_duration(value) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def probe(path: Path, ffprobe: str = "ffprobe") -> MediaInfo:
    try:
        path = path.resolve(strict=True)
        with path.open("rb"):
            size = path.stat().st_size
    except (OSError, RuntimeError) as exc:
        raise NoteFlowError("INPUT_UNREADABLE", "probe", "无法打开输入文件。") from exc
    media_format = FORMATS.get(path.suffix.lower())
    if media_format is None:
        raise NoteFlowError("UNSUPPORTED_MEDIA", "probe", "请选择 PCM WAV、MP3 或含 AAC 音轨的 MP4。")
    if size > MAX_BYTES:
        raise NoteFlowError("INPUT_LIMIT", "probe", "文件超过 200 MB，请截取片段后重试。")

    demuxer, expected_codec = media_format
    output = _run_tool(
        ffprobe, "probe", 15, "-v", "error", "-protocol_whitelist", "file", "-f", demuxer,
        "-show_entries", "stream=index,codec_type,codec_name,duration:format=duration",
        "-of", "json", "-i", str(path),
    )
    try:
        metadata = json.loads(output)
        track = next((stream for stream in metadata.get("streams", ()) if stream.get("codec_type") == "audio"), None)
        if track is None:
            raise NoteFlowError("NO_AUDIO", "probe", "文件没有音轨，请选择包含音频的文件。")
        index, codec = track["index"], track.get("codec_name", "")
        if not isinstance(index, int) or index < 0 or not isinstance(codec, str):
            raise ValueError("Invalid audio stream metadata")
        duration = _known_duration(track.get("duration"))
        # Container duration is a usable fallback for audio-only files.
        if duration is None and demuxer != "mov":
            duration = _known_duration(metadata.get("format", {}).get("duration"))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise NoteFlowError("DECODE_FAILED", "probe", "媒体探测返回了无效的音轨信息。") from exc

    supported = codec.startswith(expected_codec) if demuxer == "wav" else codec == expected_codec
    if not supported:
        raise NoteFlowError("UNSUPPORTED_MEDIA", "probe", "首条音轨的编码不受支持。")
    if duration is not None:
        _check_duration(duration, "probe")
    return MediaInfo(path, index, codec)


def normalize(info: MediaInfo, workdir: Path, ffmpeg: str = "ffmpeg") -> AudioAsset:
    wav_path = workdir / "analysis.wav"
    demuxer = FORMATS[info.path.suffix.lower()][0]
    _run_tool(
        ffmpeg, "decode", 90, "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file",
        "-f", demuxer, "-i", str(info.path), "-map", f"0:{info.stream_index}", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-t", str(MAX_SECONDS + 1), str(wav_path),
    )
    try:
        with wave.open(str(wav_path), "rb") as wav:
            frames = wav.getnframes()
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ValueError("Unexpected PCM format")
            duration = frames / SAMPLE_RATE
            _check_duration(duration, "decode")
            has_signal = False
            while frames:
                count = min(frames, 32768)
                block = wav.readframes(count)
                if len(block) != count * 2:
                    raise ValueError("Truncated PCM data")
                has_signal = has_signal or any(block)
                frames -= count
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        raise NoteFlowError("DECODE_FAILED", "decode", "解码结果不是完整的 PCM 音频。") from exc
    return AudioAsset(wav_path, duration, has_signal)
