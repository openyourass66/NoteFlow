"""Check pitch accuracy and chunk alignment on a labeled harmonic signal."""

import argparse
import json
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sr = 16000
    t = np.arange(sr * 22) / sr
    target = np.where(t < 10, 60, np.where(t < 19.5, 69, 74))
    frequency = 440 * 2 ** ((target - 69) / 12)
    phase = 2 * np.pi * np.cumsum(frequency) / sr
    samples = .18 * sum(np.sin(phase * h) / h ** 1.4 for h in range(1, 6))
    audio, output = args.output / "known-pitch.wav", args.output / "known-pitch.npz"
    sf.write(audio, samples, sr)
    worker = Path(__file__).resolve().parents[1] / "src/noteflow/pitch_worker.py"
    subprocess.run([str(args.python.resolve()), "-I", str(worker), str(audio), str(output)],
                   check=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with np.load(output, allow_pickle=False) as result:
        midi = 69 + 12 * np.log2(result["f0"] / 440)
        times = result["times"]
        expected = np.where(times < 10, 60, np.where(times < 19.5, 69, 74))
        valid = ((times > .1) & (times < 21.9) & (abs(times - 10) > .1) & (abs(times - 19.5) > .1))
        errors = abs(midi[valid] - expected[valid]) * 100
        boundary = (times > 19.9) & (times < 20.1)
        report = {
            "device": str(result["device"]),
            "median_error_cents": float(np.median(errors)),
            "p95_error_cents": float(np.quantile(errors, .95)),
            "within_50_cents": float(np.mean(errors < 50)),
            "chunk_border_max_error_cents": float(np.max(abs(midi[boundary] - 74) * 100)),
        }
    (args.output / "known-pitch-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    assert report["within_50_cents"] > .98
    assert report["chunk_border_max_error_cents"] < 30


if __name__ == "__main__":
    main()
