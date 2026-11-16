"""Match source timbre at melody-note positions against local SoundFont presets."""

import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import mido
import numpy as np

from .errors import NoteFlowError
from .export import GUZHENG_PROGRAM, PROGRAMS
from .media import SAMPLE_RATE, normalize
from .process import check_cancelled, run_tool
from .synthesis import GUZHENG_SOUNDFONT, soundfont_programs

_TEMPLATE_STEP_MS = 300
_TEMPLATE_NOTE_MS = 250
_FFT_SIZE = 8192
_HARMONICS = 12
_MAX_NOTES = 14


def _sample_notes(notes):
    suitable = [note for note in notes if 36 <= note.midi <= 96 and note.end_s - note.start_s >= .075]
    if len(suitable) <= _MAX_NOTES:
        return suitable
    return [suitable[i] for i in np.linspace(0, len(suitable) - 1, _MAX_NOTES, dtype=int)]


def _read_pcm(path):
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        if source.getframerate() != SAMPLE_RATE or source.getsampwidth() != 2 or channels not in (1, 2):
            raise ValueError("Unexpected timbre analysis audio format")
        raw = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
        return raw if channels == 1 else raw.reshape(-1, channels).mean(axis=1)


def _profile(samples, start, duration, midi):
    duration = min(duration, _TEMPLATE_NOTE_MS / 1000)
    width = min(int(duration * SAMPLE_RATE * .65), 2048)
    f0 = 440 * 2 ** ((midi - 69) / 12)
    hz = f0 * np.arange(1, _HARMONICS + 1)
    bins = hz * (_FFT_SIZE / SAMPLE_RATE)
    tolerance = np.clip(bins * .025, 4, f0 * .35 * (_FFT_SIZE / SAMPLE_RATE))
    window = np.hanning(width)
    spectra, levels = [], []
    for center in (duration * .35, duration * .67):
        first = round((start + center) * SAMPLE_RATE) - width // 2
        frame = samples[first:first + width]
        if len(frame) != width or first < 0:
            return None
        magnitude = np.abs(np.fft.rfft(frame * window, n=_FFT_SIZE))
        peaks = [
            magnitude[round(b - t):round(b + t) + 1].max() if b + t < len(magnitude) else 0
            for b, t in zip(bins, tolerance)
        ]
        level = np.linalg.norm(peaks)
        # Require appreciable energy on the melody's harmonics rather than spectral leakage from the mix.
        if level < max(1000, magnitude.max() * .14):
            return None
        spectrum = np.sqrt(peaks)
        spectra.append(spectrum / np.linalg.norm(spectrum))
        levels.append(level)
    decay = np.clip(np.log(levels[1] / levels[0]), -2, 2)
    return np.array(spectra), decay


def _render_templates(directory, soundfont, fluidsynth, programs, pitches, cancel):
    midi = mido.MidiFile(type=0, ticks_per_beat=1000)
    track = midi.add_track()
    track.append(mido.MetaMessage("set_tempo", tempo=1_000_000))
    offsets = {}
    for program in programs:
        track.append(mido.Message("program_change", program=program))
        for pitch in pitches:
            offsets[program, pitch] = len(offsets) * _TEMPLATE_STEP_MS / 1000
            track.append(mido.Message("note_on", note=pitch, velocity=80))
            track.append(mido.Message("note_off", note=pitch, time=_TEMPLATE_NOTE_MS))
            track.append(mido.Message("control_change", control=120, value=0, time=_TEMPLATE_STEP_MS - _TEMPLATE_NOTE_MS))
    source, target = directory / "presets.mid", directory / "presets.wav"
    midi.save(source)
    soundfonts = [str(soundfont)]
    if GUZHENG_PROGRAM in programs:
        # FluidSynth uses the last loaded preset when both banks contain program 107.
        soundfonts.append(str(GUZHENG_SOUNDFONT))
    run_tool(fluidsynth, "render", 30, (
        "-ni", "-R", "0", "-C", "0", "-r", str(SAMPLE_RATE), "-T", "wav",
        "-F", str(target), *soundfonts, str(source),
    ), cancel)
    return _read_pcm(target), offsets


def _match(samples, notes, directory, soundfont, fluidsynth, programs, cancel):
    observations = []
    for note in notes:
        check_cancelled(cancel)
        duration = note.end_s - note.start_s
        if (profile := _profile(samples, note.start_s, duration, note.midi)) is not None:
            observations.append((note.midi, duration, *profile))
    if len(observations) < 2:
        return None
    pitches = sorted({pitch for pitch, *_ in observations})
    templates, offsets = _render_templates(directory, soundfont, fluidsynth, programs, pitches, cancel)
    scores = []
    for program in programs:
        check_cancelled(cancel)
        similarities = []
        for pitch, duration, spectrum, decay in observations:
            expected = _profile(templates, offsets[program, pitch], duration, pitch)
            if expected is None:
                similarities.append(0)
                continue
            expected_spectrum, expected_decay = expected
            similarity = (spectrum * expected_spectrum).sum() / len(spectrum)
            similarities.append(similarity - .08 * abs(decay - expected_decay))
        scores.append((float(np.mean(similarities)), program))
    scores.sort(reverse=True)
    best, program = scores[0]
    if best >= .78 and (len(scores) == 1 or best - scores[1][0] >= .012):
        return program
    return None


def choose_program(media, notes, soundfont: Path, ffmpeg, fluidsynth, workdir, cancel):
    """Return a playable program and whether the original timbre was matched."""
    check_cancelled(cancel)
    try:
        available = soundfont_programs(soundfont)
    except (OSError, ValueError, struct.error):
        return 0, False
    programs = tuple(program for program in PROGRAMS.values()
                     if program in available and program != GUZHENG_PROGRAM)
    fallback = next(iter(programs), min(available - {GUZHENG_PROGRAM}, default=0))
    try:
        if GUZHENG_PROGRAM in soundfont_programs(GUZHENG_SOUNDFONT):
            programs += (GUZHENG_PROGRAM,)
    except (OSError, ValueError, struct.error):
        pass
    notes = _sample_notes(notes)
    if len(programs) < 2 or len(notes) < 2:
        return fallback, False
    try:
        with TemporaryDirectory(prefix="timbre-", dir=workdir) as folder:
            directory = Path(folder)
            original = normalize(media, directory, ffmpeg, cancel=cancel)
            samples = _read_pcm(original.path)
            program = _match(samples, notes, directory, soundfont, fluidsynth, programs, cancel)
    except (NoteFlowError, OSError, ValueError, EOFError, wave.Error):
        return fallback, False
    return (program, True) if program is not None else (fallback, False)
