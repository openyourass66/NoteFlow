import json
import shutil
import subprocess
import wave
from threading import Event

import pytest

from noteflow import analysis, media, transcription
from noteflow.__main__ import main
from noteflow.errors import NoteFlowError
from noteflow.score import ScoreSettings, build_score
from poc.fixtures import melody, write_wave


@pytest.fixture(scope="module")
def tools():
    tools = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}
    if not all(tools.values()):
        pytest.skip("FFmpeg and ffprobe must be on PATH")
    return tools


@pytest.fixture(scope="module")
def samples(tmp_path_factory, tools):
    root = tmp_path_factory.mktemp("中文 旋律")
    notes = melody()
    wav = root / "自制样本.wav"
    mp3 = wav.with_suffix(".mp3")
    mp4 = wav.with_suffix(".mp4")
    m4a = wav.with_suffix(".m4a")
    mislabeled = root / "实际为 AAC 的文件.mp3"
    video_only = root / "video-only.mp4"
    corrupt = root / "corrupt.wav"
    long_audio = root / "long.wav"
    boundary = root / "boundary.wav"
    silence = root / "silence.wav"

    def ffmpeg(*args):
        subprocess.run([tools["ffmpeg"], "-nostdin", "-v", "error", *args], check=True, timeout=30)

    write_wave(wav, 10, notes)
    write_wave(silence, 1)
    write_wave(long_audio, 121.25)
    write_wave(boundary, 120)
    corrupt.write_bytes(b"not a WAV file")
    ffmpeg("-i", str(wav), "-c:a", "libmp3lame", str(mp3))
    ffmpeg("-i", str(wav), "-c:a", "aac", str(m4a))
    shutil.copyfile(m4a, mislabeled)
    ffmpeg("-f", "lavfi", "-i", "color=s=160x90:r=10", "-i", str(wav), "-i", str(silence),
           "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "aac",
           "-t", "10", str(mp4))
    ffmpeg("-f", "lavfi", "-i", "color=s=160x90:r=10", "-t", "1", "-c:v", "mpeg4", str(video_only))
    return {"wav": wav, "mp3": mp3, "mp4": mp4, "m4a": m4a, "aac_named_mp3": mislabeled,
            "no_audio": video_only, "corrupt": corrupt, "long": long_audio, "boundary": boundary, "silence": silence}


@pytest.mark.parametrize(("kind", "index", "codec"), [
    ("wav", 0, "pcm_s16le"), ("mp3", 0, "mp3"), ("mp4", 1, "aac"),
    ("m4a", 0, "aac"), ("aac_named_mp3", 0, "aac"),
])
def test_formats_transcribe_the_same_melody(samples, tools, kind, index, codec):
    result = analysis.analyze(samples[kind], **tools)
    assert result.media.stream_index == index
    assert result.media.codec == codec
    assert result.duration_s == pytest.approx(10, abs=0.05)
    assert [note.midi for note in result.notes] == [pitch for _, _, pitch in melody()]
    for note, (expected_start, _, _) in zip(result.notes, melody()):
        assert note.start_s == pytest.approx(expected_start, abs=0.05)


@pytest.mark.parametrize("kind", ["wav", "mp3", "mp4", "m4a", "aac_named_mp3"])
def test_original_playback_decodes_first_track(samples, tools, kind, tmp_path):
    source = samples[kind]
    info = media.probe(source, tools["ffprobe"])
    target = tmp_path / "original.wav"
    assert media.decode_original(info, target, tools["ffmpeg"], Event()) == target
    with wave.open(str(target), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (2, 2, 48000)
        assert wav.getnframes() / wav.getframerate() == pytest.approx(10, abs=0.05)
        assert any(wav.readframes(48000))  # The second MP4 track is silent.


def test_transcribed_melody_survives_louder_sustained_accompaniment(tmp_path, tools):
    lead, bass, mixed = (tmp_path / name for name in ("lead.wav", "bass.wav", "mixed.wav"))
    expected = melody()
    write_wave(lead, 9, expected)
    write_wave(bass, 9, [(0, 9, 43)])
    subprocess.run([tools["ffmpeg"], "-nostdin", "-v", "error", "-i", str(lead), "-i", str(bass),
                    "-filter_complex", "amix=inputs=2:weights='0.85 1.15':normalize=0", str(mixed)],
                   check=True, timeout=30)
    analysis_result = analysis.analyze(mixed, **tools)
    assert any(n.midi == 43 for n in analysis_result.notes)
    score = build_score(analysis_result.notes, ScoreSettings(bpm=80))
    assert [n.midi for n in score.grid.notes] == [pitch for _, _, pitch in expected]
    assert [n.start_s for n in score.melody] == pytest.approx([start for start, _, _ in expected], abs=0.05)


@pytest.mark.parametrize("accompaniment", [False, True], ids=["fast-notes", "backing-during-rests"])
def test_melody_analysis_recovers_lead_from_basic_pitch_frames(tmp_path, tools, accompaniment):
    expected = melody()
    if not accompaniment:
        expected = [(i * 0.25, i * 0.25 + 0.09, pitch) for i, (_, _, pitch) in enumerate(expected)]
    wav = tmp_path / "melody.wav"
    write_wave(wav, 10, expected, accompaniment=accompaniment)
    info = media.probe(wav, tools["ffprobe"])

    result = analysis.analyze_media(info, ffmpeg=tools["ffmpeg"], melody_only=True, verify_pitch=True)

    assert [note.midi for note in result.notes] == [pitch for _, _, pitch in expected]
    assert [note.start_s for note in result.notes] == pytest.approx([start for start, _, _ in expected], abs=0.05)
    assert all(left.end_s <= right.start_s for left, right in zip(result.notes, result.notes[1:]))
    assert (result.candidate_overlap > analysis.HEAVY_OVERLAP) == accompaniment


@pytest.mark.parametrize(("kind", "code", "stage"), [
    ("no_audio", "NO_AUDIO", "probe"), ("corrupt", "DECODE_FAILED", "probe"),
    ("long", "INPUT_LIMIT", "probe"), ("silence", "NO_NOTES", "transcribe"),
])
def test_invalid_media_returns_specific_errors(samples, tools, monkeypatch, kind, code, stage):
    def load_model():
        pytest.fail("Invalid or silent media must be rejected before loading the model")

    monkeypatch.setattr(transcription, "_load_model", load_model)
    with pytest.raises(NoteFlowError) as error:
        analysis.analyze(samples[kind], **tools)
    assert (error.value.code, error.value.stage) == (code, stage)


def test_input_size_is_checked_before_probing(samples, monkeypatch):
    monkeypatch.setattr(media, "MAX_BYTES", 1)
    with pytest.raises(NoteFlowError) as error:
        media.probe(samples["wav"], ffprobe="missing-ffprobe")
    assert error.value.code == "INPUT_LIMIT"


def test_exact_length_limit(samples, tools, tmp_path):
    info = media.probe(samples["boundary"], tools["ffprobe"])
    asset = media.normalize(info, tmp_path, tools["ffmpeg"])
    assert asset.duration_s == 120


def test_decode_checks_length_when_probe_duration_was_unknown(samples, tools, tmp_path):
    info = media.MediaInfo(samples["long"], 0, "pcm_s16le", "wav")
    with pytest.raises(NoteFlowError) as error:
        media.normalize(info, tmp_path, tools["ffmpeg"])
    assert (error.value.code, error.value.stage) == ("INPUT_LIMIT", "decode")


def test_analysis_cleans_temporary_audio_on_cancellation(samples, tools, monkeypatch):
    seen = []

    def cancel(asset):
        assert asset.path.is_file()
        seen.append(asset.path.parent)
        raise KeyboardInterrupt

    monkeypatch.setattr(analysis, "transcribe", cancel)
    with pytest.raises(KeyboardInterrupt):
        analysis.analyze(samples["wav"], **tools)
    assert seen and not seen[0].exists()


def test_cli_stdout_is_json(samples, tools, capsys):
    exit_code = main([str(samples["wav"]), "--ffmpeg", tools["ffmpeg"], "--ffprobe", tools["ffprobe"]])
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["media"]["name"] == samples["wav"].name
    assert len(result["notes"]) == len(melody())
