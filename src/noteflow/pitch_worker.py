"""Isolated optional pitch worker; executed by the configured inference Python."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--minimum", type=int, default=36)
    parser.add_argument("--maximum", type=int, default=96)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    import numpy as np
    import librosa
    import torch
    import torchcrepe

    torch.set_num_threads(4)
    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device == "auto":
        device = "cpu"
    samples, sr = librosa.load(args.audio, sr=16000, mono=True)
    minimum = max(50.0, float(librosa.midi_to_hz(args.minimum)))
    maximum = min(torchcrepe.MAX_FMAX, float(librosa.midi_to_hz(args.maximum)))
    if minimum >= maximum:
        length = (len(samples) + 159) // 160
        np.savez_compressed(args.output, f0=np.zeros(length), confidence=np.zeros(length),
                            times=np.arange(length) * .01, device=device)
        return
    def decode(probabilities):
        # Keep local acoustic candidates here. The application performs the
        # sequence decoding after combining them with note/onset evidence.
        bins = probabilities.argmax(dim=1)
        indices = torch.arange(360, device=probabilities.device)[None, :, None]
        weights = torch.where((indices - bins[:, None]).abs() <= 4,
                              probabilities.clamp(min=0), 0)
        cents = 1997.3794084376191 + 20 * indices
        center = (weights * cents).sum(dim=1) / weights.sum(dim=1).clamp(min=1e-8)
        return bins, 10 * 2 ** (center / 1200)

    pitch, confidence = [], []
    # Overlap context avoids creating pitch discontinuities at chunk borders.
    step, context = 16000 * 20, 16000 // 2
    for first in range(0, len(samples), step):
        last = min(len(samples), first + step)
        lo, hi = max(0, first - context), min(len(samples), last + context)
        signal = torch.from_numpy(samples[lo:hi])[None]
        with torch.inference_mode():
            f0, periodicity = torchcrepe.predict(
                signal, sr, 160, minimum, maximum, "full", batch_size=256,
                device=device, return_periodicity=True, decoder=decode,
            )
        start = (first - lo) // 160
        stop = start + (last - first + 159) // 160
        pitch.extend(f0[0, start:stop].cpu().numpy())
        confidence.extend(periodicity[0, start:stop].cpu().numpy())
    np.savez_compressed(args.output, f0=np.asarray(pitch), confidence=np.asarray(confidence),
                        times=np.arange(len(pitch)) * 0.01, device=device)


if __name__ == "__main__":
    main()
