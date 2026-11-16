from pathlib import Path
from shutil import which
from threading import Event

import pytest

from noteflow.instruments import choose_program
from noteflow.media import probe
from noteflow.notes import NoteEvent
from noteflow.score import ScoreSettings, build_score
from noteflow.synthesis import render_preview


@pytest.fixture(scope="module")
def tools():
    pytest.importorskip("PySide6")
    from noteflow.desktop_settings import _default_tools

    tools = _default_tools()
    if not tools.soundfont or not all(which(exe) for exe in (tools.ffmpeg, tools.ffprobe, tools.fluidsynth)):
        pytest.skip("Instrument matching requires FFmpeg, FluidSynth and a GM SoundFont")
    return tools


@pytest.mark.parametrize("program", [24, 40, 65])
def test_matches_reference_timbre_using_original_audio(tools, tmp_path, program):
    soundfont = Path(tools.soundfont)
    score = build_score(tuple(
        NoteEvent(str(i), i * .32, i * .32 + .26, pitch, .8, 80)
        for i, pitch in enumerate((62, 64, 69, 65, 72, 67, 64, 74))
    ), ScoreSettings())
    audio = tmp_path / "original.wav"
    render_preview(score, program, soundfont, audio, tools.fluidsynth, Event())
    media = probe(audio, tools.ffprobe)
    assert choose_program(media, score.melody, soundfont, tools.ffmpeg, tools.fluidsynth,
                          tmp_path, Event()) == (program, True)
    assert choose_program(media, score.melody[:1], soundfont, tools.ffmpeg, tools.fluidsynth,
                          tmp_path, Event()) == (0, False)
