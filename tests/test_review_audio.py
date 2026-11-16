import io
import wave
from dataclasses import replace

import numpy as np
import pytest

from noteflow.desktop_settings import _default_tools
from noteflow.review_audio import RATE, ReviewAudio
from noteflow.review_calibration import prepare_cases
from noteflow.score import ScoreSettings


def test_real_render_bundle_keeps_timing_offsets_silence_and_pitch_variants(tmp_path):
    import shutil
    from pathlib import Path
    tools = _default_tools()
    if not shutil.which(tools.ffmpeg) or not shutil.which(tools.fluidsynth) or not Path(tools.soundfont).is_file():
        pytest.skip("Requires the playback tools")
    media, clean, wrong, _, _ = prepare_cases(tmp_path / "cases")
    audio = ReviewAudio(media, ScoreSettings(), tools, tmp_path / "audio", None)
    data, labels = audio.bundle([("A", clean), ("B", wrong)], 0, 8)
    with wave.open(io.BytesIO(data)) as wav:
        assert wav.getframerate() == RATE and wav.getnframes() == 26 * RATE
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    assert not samples[8 * RATE:9 * RATE].any()
    assert not samples[17 * RATE:18 * RATE].any()
    assert np.any(samples[9 * RATE:17 * RATE] != samples[18 * RATE:26 * RATE])
    assert "9.0000–17.0000" in labels and "18.0000–26.0000" in labels
    assert not samples[:int(.35 * RATE)].any()
    assert not samples[9 * RATE:round(9.35 * RATE)].any()
    cropped, _ = audio.bundle([("A", clean)], 2, 4)
    with wave.open(io.BytesIO(cropped)) as wav:
        assert wav.getnframes() == 5 * RATE


def test_local_models_recover_deliberate_semitone_error_on_known_audio(tmp_path):
    import shutil
    from noteflow.review import ReviewIssue
    from noteflow.review_repair import LocalRepair, collect_evidence
    from noteflow.media import normalize
    from noteflow.options import AnalysisOptions
    tools = _default_tools()
    if not shutil.which(tools.ffmpeg):
        pytest.skip("Requires FFmpeg")
    media, clean, _, _, _ = prepare_cases(tmp_path)
    asset = normalize(media, tmp_path, tools.ffmpeg)
    evidence = collect_evidence(asset, AnalysisOptions())
    wrong = tuple(replace(n, midi=n.midi + 1) if i == 3 else n for i, n in enumerate(clean))
    issue = (ReviewIssue(wrong[3].start_s, wrong[3].end_s, "pitch", "偏高"),)
    fixed = LocalRepair(lambda _: evidence)(wrong, issue)
    assert fixed[3].midi == clean[3].midi
    assert fixed[:3] == wrong[:3] and fixed[4:] == wrong[4:]


def test_review_service_uses_rendered_audio_local_repair_and_complete_final_review(tmp_path, monkeypatch):
    import json
    import shutil
    from pathlib import Path
    from noteflow import review_qwen
    from noteflow.analysis import AnalysisResult
    from noteflow.review import ReviewLimits
    from noteflow.review_qwen import QwenConfig
    from noteflow.review_service import review_score
    from noteflow.score import build_score
    tools = replace(_default_tools(), pitch_python="")
    if not shutil.which(tools.ffmpeg) or not shutil.which(tools.fluidsynth) or not Path(tools.soundfont).is_file():
        pytest.skip("Requires the playback tools")
    media, clean, _, _, _ = prepare_cases(tmp_path / "source")
    wrong = tuple(replace(n, midi=n.midi + 1) if i == 3 else n for i, n in enumerate(clean))
    responses = iter([
        {"status": "issues", "summary": "受控测试回复", "issues": [{"start_s": 2.95, "end_s": 3.60,
             "kind": "pitch", "explanation": "测试中已知的偏高音符"}]},
        {"preference": "B", "summary": "受控比较"}, {"preference": "A", "summary": "受控比较"},
        {"status": "pass", "summary": "受控测试回复", "issues": []},
    ])
    calls = []
    def simulated_request(config, audio, prompt, cancel):
        with wave.open(io.BytesIO(audio)) as wav:
            calls.append(wav.getnframes() / wav.getframerate())
        return json.dumps(next(responses)), {"total_tokens": 100}
    monkeypatch.setattr(review_qwen, "request", simulated_request)
    result = review_score(AnalysisResult(media, 8, wrong), build_score(wrong, ScoreSettings()), tools,
                          QwenConfig("https://dashscope.aliyuncs.com/compatible-mode/v1", api_key="test-only"),
                          tmp_path / "session", limits=ReviewLimits(), start_s=0, end_s=8)
    assert result.status == "passed" and result.notes[3].midi == clean[3].midi
    assert calls == [17, 26, 26, 17]
    report = json.loads((tmp_path / "session/report.json").read_text(encoding="utf-8"))
    assert report["usage"]["total_tokens"] == 400 and report["accuracy"] is None


def test_candidate_audition_has_three_aligned_real_audio_files(tmp_path):
    import shutil
    from pathlib import Path
    from noteflow.analysis import AnalysisResult
    from noteflow.review import RepairCandidate, fingerprint
    from noteflow.review_service import prepare_audition
    from noteflow.score import build_score
    tools = _default_tools()
    if not shutil.which(tools.ffmpeg) or not shutil.which(tools.fluidsynth) or not Path(tools.soundfont).is_file():
        pytest.skip("Requires the playback tools")
    media, clean, wrong, _, _ = prepare_cases(tmp_path / "source")
    candidate = RepairCandidate(clean, fingerprint(wrong), 0, 8, "恢复已知旋律")
    paths, first, last = prepare_audition(AnalysisResult(media, 8, wrong), build_score(wrong, ScoreSettings()),
                                         candidate, tools, tmp_path / "audition")
    assert (first, last) == (0, 8) and len(paths) == 3
    samples = []
    for path in paths:
        with wave.open(str(path)) as wav:
            assert wav.getnframes() == RATE * 8 and wav.getframerate() == RATE
            samples.append(np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2"))
    assert np.any(samples[1] != samples[2])
    assert all(not track[:round(.35 * RATE)].any() for track in samples)
