"""Time-aligned, fixed-piano listening material for remote review."""

import io
import wave
from pathlib import Path

import numpy as np

from .media import normalize, MediaInfo
from .process import check_cancelled, run_tool
from .review import fingerprint
from .score import build_score
from .synthesis import render_preview

RATE = 24000


def read_pcm(path: Path):
    with wave.open(str(path), "rb") as stream:
        if (stream.getsampwidth(), stream.getnchannels()) != (2, 1):
            raise ValueError("Expected mono PCM16")
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").copy(), stream.getframerate()


def wav_bytes(samples, rate=RATE):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return output.getvalue()


def _level(samples):
    # One gain for a whole clip; no time stretching, pitch shifting or gate.
    peak = max(1, int(np.max(np.abs(samples.astype(np.int32))))) if len(samples) else 1
    return np.clip(samples.astype(np.float64) * min(8.0, 24000 / peak), -32767, 32767).astype("<i2")


class ReviewAudio:
    def __init__(self, media, settings, tools, folder, cancel):
        self.media, self.settings, self.tools = media, settings, tools
        self.folder, self.cancel = Path(folder), cancel
        self.folder.mkdir(parents=True, exist_ok=True)
        self.reference = self.folder / "reference.wav"
        run_tool(tools.ffmpeg, "decode", 90, (
            "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file",
            "-f", media.demuxer, "-i", str(media.path), "-map", f"0:{media.stream_index}",
            "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le",
            "-t", "121", str(self.reference),
        ), cancel)
        self._reference, _ = read_pcm(self.reference)
        self._renders = {}

    def performance(self, notes):
        signature = fingerprint(notes)
        if signature not in self._renders:
            check_cancelled(self.cancel)
            if not notes:
                return np.zeros_like(self._reference)
            rendered = self.folder / f"{signature}.wav"
            converted = self.folder / f"{signature}-mono.wav"
            render_preview(build_score(notes, self.settings), 0, Path(self.tools.soundfont),
                           rendered, self.tools.fluidsynth, self.cancel, original_timing=True)
            run_tool(self.tools.ffmpeg, "render", 90, (
                "-nostdin", "-v", "error", "-i", str(rendered), "-ac", "1", "-ar", str(RATE),
                "-c:a", "pcm_s16le", str(converted),
            ), self.cancel)
            self._renders[signature] = read_pcm(converted)[0]
        return self._renders[signature]

    def clips(self, variants, first, last):
        """Equally long aligned clips, also used for local A/B audition."""
        check_cancelled(self.cancel)
        start, end = round(first * RATE), round(last * RATE)
        if not 0 <= start < end <= len(self._reference) + 2:
            raise ValueError("Invalid listening interval")
        tracks = [("R（原曲）", self._reference)]
        tracks += [(label, self.performance(notes)) for label, notes in variants]
        result = []
        for label, samples in tracks:
            clip = samples[start:end]
            clip = np.pad(clip, (0, max(0, end - start - len(clip))))
            result.append((label, _level(clip)))
        return result

    def bundle(self, variants, first, last):
        """One explicitly labeled WAV for the cloud listening comparison."""
        if last - first > 20.00001:
            raise ValueError("Invalid listening interval")
        pieces, labels, cursor = [], [], 0
        for label, clip in self.clips(variants, first, last):
            pieces.append(clip)
            labels.append(f"{label}: 合集 {cursor / RATE:.4f}–{(cursor + len(clip)) / RATE:.4f} 秒")
            pieces.append(np.zeros(RATE, dtype="<i2"))
            cursor += len(clip) + RATE
        return wav_bytes(np.concatenate(pieces[:-1])), "\n".join(labels)

    def evidence_audio(self, stem=None):
        media = MediaInfo(stem, 0, "pcm_s16le", "wav") if stem else self.media
        return normalize(media, self.folder, self.tools.ffmpeg, cancel=self.cancel, filename="evidence.wav")
