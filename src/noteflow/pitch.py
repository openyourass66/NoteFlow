"""Run the optional neural pitch estimator in a cancellable process."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

import numpy as np

from .media import AudioAsset
from .options import AnalysisOptions
from .process import run_tool


def estimate_pitch(audio: AudioAsset, python: str, options: AnalysisOptions,
                   cancel: Event | None = None):
    with TemporaryDirectory(prefix="pitch-", dir=audio.path.parent) as folder:
        output = Path(folder) / "pitch.npz"
        run_tool(python, "pitch", 1200, (
            "-I", str(Path(__file__).with_name("pitch_worker.py")), str(audio.path), str(output),
            "--minimum", str(options.pitch_min), "--maximum", str(options.pitch_max),
        ), cancel)
        with np.load(output, allow_pickle=False) as data:
            return data["times"].copy(), data["f0"].copy(), data["confidence"].copy(), str(data["device"])
