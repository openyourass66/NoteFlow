"""Run the Windows M0 media, model, synthesis, and playback checks."""

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import time
import wave
from array import array
from bisect import bisect_left
from pathlib import Path

from fixtures import PROGRAMS, SAMPLE_RATE, melody, write_midi, write_wave


def run_tool(exe, *args):
    process = subprocess.run(
        [str(exe), *map(str, args)], capture_output=True, timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()[-1500:]
        raise RuntimeError(f"{exe.name} returned {process.returncode}: {detail}")
    return process.stdout.decode("utf-8", errors="replace")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_wave(path, rate, channels):
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (rate, channels, 2):
            raise RuntimeError(f"Unexpected WAV format: {path.name}")
        if not frames:
            raise RuntimeError(f"Empty WAV: {path.name}")
        samples = array("h", wav.readframes(frames))
        if len(samples) != frames * channels:
            raise RuntimeError(f"Truncated WAV: {path.name}")
    return {"sample_rate": rate, "channels": channels, "frames": frames,
            "duration_s": frames / rate, "peak_pcm16": max(abs(value) for value in samples)}


def normalize(ffmpeg, ffprobe, source, target):
    metadata = json.loads(run_tool(ffprobe, "-v", "error", "-protocol_whitelist", "file",
                                   "-show_streams", "-show_format", "-of", "json", source))
    track = next((stream for stream in metadata["streams"] if stream["codec_type"] == "audio"), None)
    if track is None:
        raise RuntimeError("NO_AUDIO")
    run_tool(ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-i", source,
             "-map", f"0:{track['index']}", "-vn", "-sn", "-dn", "-ac", 1, "-ar", SAMPLE_RATE,
             "-c:a", "pcm_s16le", "-t", 121, target)
    info = inspect_wave(target, SAMPLE_RATE, 1)
    if info["duration_s"] > 120:
        raise RuntimeError("INPUT_LIMIT")
    return {"stream_index": track["index"], "codec": track["codec_name"], **info}


def monophonic(events, duration):
    candidates = []
    for index, (start, end, midi, strength, *_rest) in enumerate(events):
        if not all(map(math.isfinite, (start, end, midi))) or not 0 <= midi <= 127:
            continue
        start, end = max(0, start), min(duration, end)
        if end > start:
            strength = max(0.0, min(1.0, strength)) if math.isfinite(strength) else 0.5
            candidates.append((float(start), float(end), int(midi), float(strength), index))
    candidates.sort(key=lambda note: (-note[3], note[0], note[0] - note[1], note[2], note[4]))
    accepted, starts = [], []
    for note in candidates:
        start, end = note[:2]
        index = bisect_left(starts, start)
        if index and accepted[index - 1][1] > start:
            continue
        if index < len(starts) and starts[index] < end:
            continue
        starts.insert(index, start)
        accepted.insert(index, note)
    return [note[:4] for note in accepted], len(candidates) - len(accepted)


def compare(expected, predicted):
    errors, duration_errors = [], []
    for pitch in {note[2] for note in expected}:
        candidates = iter(sorted(note[:2] for note in predicted if note[2] == pitch))
        actual = next(candidates, None)
        for start, end in sorted(note[:2] for note in expected if note[2] == pitch):
            while actual is not None and actual[0] < start - 0.05:
                actual = next(candidates, None)
            if actual is not None and actual[0] <= start + 0.05:
                errors.append(abs(actual[0] - start) * 1000)
                duration_errors.append(abs((actual[1] - actual[0]) - (end - start)) * 1000)
                actual = next(candidates, None)
    matched = len(errors)
    total = len(expected) + len(predicted)
    return {"matched": matched, "missed": len(expected) - matched,
            "unmatched_predictions": len(predicted) - matched,
            "precision": matched / len(predicted) if predicted else (0.0 if expected else None),
            "recall": matched / len(expected) if expected else None,
            "f1": 2 * matched / total if total else None,
            "mean_onset_error_ms": statistics.mean(errors) if matched else None,
            "median_duration_error_ms": statistics.median(duration_errors) if matched else None}


def peak_memory_mib():
    if platform.system() != "Windows":
        return None

    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD),
                    ("peak_working_set", ctypes.c_size_t), ("other", ctypes.c_size_t * 7)]

    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    get_memory.restype = wintypes.BOOL
    counters = MemoryCounters(size=ctypes.sizeof(MemoryCounters))
    if not get_memory(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.size):
        raise ctypes.WinError()
    return round(counters.peak_working_set / 2**20, 1)


def prepare_samples(args, work):
    notes = melody()
    pcm = work / "旋律 样本.wav"
    mp3 = pcm.with_suffix(".mp3")
    video = pcm.with_suffix(".mp4")
    mix = work / "synthetic-mix.wav"
    silence = work / "silence.wav"
    write_wave(pcm, 10, notes)
    write_wave(mix, 10, notes, accompaniment=True)
    write_wave(silence, 3)
    write_midi(work / "reference.mid", notes, PROGRAMS["piano"])
    run_tool(args.ffmpeg, "-nostdin", "-v", "error", "-i", pcm, "-c:a", "libmp3lame", mp3)
    run_tool(args.ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=s=160x90:r=10",
             "-i", pcm, "-map", "0:v", "-map", "1:a", "-c:v", "mpeg4", "-c:a", "aac",
             "-shortest", video)
    cases = [(name, path, notes, "synthetic")
             for name, path in (("pcm", pcm), ("mp3", mp3), ("mp4", video))]
    cases.extend([("silence", silence, [], "silence"), ("synthetic_mix", mix, notes, "synthetic_mix")])
    for index in range(args.hot_runs):
        path = work / f"hot-{index + 1}.wav"
        long_notes = [(start, end, pitch + index) for start, end, pitch in melody(3)]
        write_wave(path, 30, long_notes)
        cases.append((path.stem, path, long_notes, "performance"))
    return cases


def load_recordings(manifest):
    if manifest is None:
        return []
    entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
    cases = []
    for index, entry in enumerate(entries, 1):
        category = entry["category"]
        if category not in {"solo", "humming", "mix"}:
            raise ValueError(f"Recording {index} has an unknown category: {category}")
        path = existing_file(manifest.parent / entry["file"])
        notes = []
        for start, end, pitch in entry["notes"]:
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end
                    and type(pitch) is int and 0 <= pitch <= 127):
                raise ValueError(f"Recording {index} has an invalid reference note")
            notes.append((start, end, pitch))
        cases.append((f"recording-{index}", path, notes, category))
    return cases


def check_model(args, work, cases, report):
    start = time.perf_counter()
    os.environ.setdefault("NUMBA_CACHE_DIR", str(work / "numba-cache"))
    import basic_pitch
    from basic_pitch.inference import Model, predict

    model_path = Path(basic_pitch.__file__).parent / "saved_models" / "icassp_2022" / "nmp.onnx"
    model = Model(model_path)
    providers = model.model.get_providers() if model.model_type == Model.MODEL_TYPES.ONNX else []
    if providers != ["CPUExecutionProvider"]:
        raise RuntimeError(f"Expected ONNX CPU, got {model.model_type} {providers}")
    report["model"] = {"sha256": sha256(model_path), "providers": providers,
                       "import_and_load_s": time.perf_counter() - start,
                       "thresholds": {"onset": 0.5, "frame": 0.3, "minimum_note_ms": 127.70}}
    for name, source, expected, category in cases:
        start = time.perf_counter()
        wav = work / f"{name}-analysis.wav"
        info = normalize(args.ffmpeg, args.ffprobe, source, wav)
        decode_seconds = time.perf_counter() - start
        infer_start = time.perf_counter()
        events = []
        if info["peak_pcm16"]:
            _, _, events = predict(wav, model_or_model_path=model, onset_threshold=0.5,
                                   frame_threshold=0.3, minimum_note_length=127.70)
        selected, dropped = monophonic(events, info["duration_s"])
        report["cases"][name] = {
            **info, "input": source.name, "category": category, "sha256": sha256(source), "reference": expected,
            "raw_event_count": len(events), "overlap_drops": dropped, "notes": selected,
            "decode_s": decode_seconds, "inference_and_selection_s": time.perf_counter() - infer_start,
            "peak_process_mib": peak_memory_mib(), "accuracy": compare(expected, selected),
        }
        print(f"{name}: {len(selected)} notes", flush=True)
        if name in {"pcm", "mp3", "mp4"} and not selected:
            raise RuntimeError(f"No model output for {name}")


def render_instruments(args, work, report):
    for name, program in PROGRAMS.items():
        midi = work / f"{name}.mid"
        wav = work / f"{name}.wav"
        write_midi(midi, melody(), program)
        run_tool(args.fluidsynth, "-ni", "-r", 44100, "-T", "wav", "-F", wav, args.sf2, midi)
        info = inspect_wave(wav, 44100, 2)
        if info["peak_pcm16"] < 100:
            raise RuntimeError(f"Inaudible render: {name}")
        report["instruments"][name] = {**info, "program": program, "sha256": sha256(wav)}
    hashes = {item["sha256"] for item in report["instruments"].values()}
    if len(hashes) != len(PROGRAMS):
        raise RuntimeError("Some instrument renders are identical")


def existing_file(value):
    path = Path(value).resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"File not found: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ffmpeg", "ffprobe", "fluidsynth", "sf2"):
        parser.add_argument(f"--{name}", type=existing_file, required=True)
    parser.add_argument("--output", type=Path, default=Path(".poc-output"))
    parser.add_argument("--recordings", type=existing_file, help="Optional annotated recording manifest (JSON)")
    parser.add_argument("--hot-runs", type=int, choices=range(4), default=3)
    parser.add_argument("--qt", action="store_true", help="Run Qt playback against the default output")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="m0-", dir=args.output.resolve()))
    report = {"python": platform.python_version(), "platform": platform.platform(), "packages": {},
              "cases": {}, "instruments": {}, "errors": []}

    stage = "environment"
    try:
        for name in ("PySide6", "basic-pitch", "onnxruntime", "librosa", "mido", "numpy",
                     "scipy", "numba", "soundfile"):
            report["packages"][name] = importlib.metadata.version(name)
        report["tools"] = {"ffmpeg": run_tool(args.ffmpeg, "-version").splitlines()[0],
                           "ffprobe": run_tool(args.ffprobe, "-version").splitlines()[0],
                           "fluidsynth": run_tool(args.fluidsynth, "--version").splitlines()[0],
                           "sf2_sha256": sha256(args.sf2)}
        stage = "fixtures"
        cases = prepare_samples(args, work)
        stage = "synthesis"
        render_instruments(args, work, report)
        stage = "inference"
        cases.append(("sf2_solo", work / "piano.wav", melody(), "synthetic_sf2"))
        cases.extend(load_recordings(args.recordings))
        check_model(args, work, cases, report)
        stage = "playback"
        if args.qt:
            from playback import check_playback

            report["qt"] = check_playback([work / f"{name}.wav" for name in PROGRAMS])
            if not all(result["ok"] for result in report["qt"]["files"].values()):
                raise RuntimeError("Qt playback or stop check failed")
    except Exception as error:
        report["errors"].append({"stage": stage, "type": type(error).__name__, "detail": str(error)})
        print(f"{stage}: {error}", flush=True)
    finally:
        report_path = work / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(report_path, flush=True)
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
