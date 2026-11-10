import shutil
from threading import Event, Timer
from time import monotonic

import pytest

from noteflow.process import Cancelled, run_tool


def test_cancel_interrupts_a_running_media_tool():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg must be on PATH")
    cancel = Event()
    timer = Timer(0.25, cancel.set)
    started = monotonic()
    timer.start()
    try:
        with pytest.raises(Cancelled):
            run_tool(ffmpeg, "decode", 30, (
                "-nostdin", "-v", "error", "-re", "-f", "lavfi", "-i", "anullsrc", "-t", "15", "-f", "null", "-",
            ), cancel)
    finally:
        timer.cancel()
    assert monotonic() - started < 5
