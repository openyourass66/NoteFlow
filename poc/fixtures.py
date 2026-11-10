"""Generate an original melody, its annotations, and repeatable test media."""

import math
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 22050
PHRASE = (60, 62, 64, 67, 65, 64, 62, 69, 67, 65, 64, 60)
PROGRAMS = {"piano": 0, "nylon_guitar": 24, "violin": 40}


def melody(repeats=1):
    return [(index * 0.75, index * 0.75 + 0.5, pitch)
            for index, pitch in enumerate(PHRASE * repeats)]


def write_midi(path, notes, program):
    import mido

    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = midi.add_track()
    tempo = mido.bpm2tempo(120)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo))
    track.append(mido.Message("program_change", program=program))
    previous = 0
    for start, end, pitch in notes:
        start_tick = round(mido.second2tick(start, 480, tempo))
        end_tick = round(mido.second2tick(end, 480, tempo))
        track.append(mido.Message("note_on", note=pitch, velocity=80, time=start_tick - previous))
        track.append(mido.Message("note_off", note=pitch, time=end_tick - start_tick))
        previous = end_tick
    midi.save(path)


def write_wave(path: Path, seconds, notes=(), accompaniment=False):
    samples = [0.0] * round(seconds * SAMPLE_RATE)
    for start, end, pitch in notes:
        frequency = 440 * 2 ** ((pitch - 69) / 12)
        first = round(start * SAMPLE_RATE)
        last = round(end * SAMPLE_RATE)
        for index in range(first, last):
            phase = math.tau * frequency * (index - first) / SAMPLE_RATE
            envelope = min(1, (index - first) / 200, (last - index) / 500)
            samples[index] += envelope * (0.36 * math.sin(phase) + 0.10 * math.sin(2 * phase))
    if accompaniment:
        for index in range(len(samples)):
            t = index / SAMPLE_RATE
            samples[index] += 0.23 * math.sin(math.tau * 130.81 * t) * (1 - t % 0.75 / 0.75)

    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        wav.writeframes(array("h", (round(sample * 32767) for sample in samples)).tobytes())
