"""Command-line entry point for local melody transcription."""

import argparse
import json
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from .media import probe
from .options import AnalysisOptions
from .pipeline import run_pipeline
from .errors import NoteFlowError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="noteflow", description="识别本地音频或视频中的音符。")
    parser.add_argument("source", type=Path, help="PCM WAV、MP3 或含 AAC 音轨的 MP4 / M4A")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg 路径，默认从 PATH 查找")
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe 路径，默认从 PATH 查找")
    parser.add_argument("--demucs-python", default="", help="已安装 Demucs 的 Python 路径")
    parser.add_argument("--pitch-python", default="", help="可选：已安装 torchcrepe 的 Python 路径")
    parser.add_argument("--target", choices=("instrument", "vocal"), default="instrument", help="提取目标")
    parser.add_argument("--source", dest="input_mode", choices=("auto", "original", "separated"), default="auto")
    parser.add_argument("--pitch-min", type=int, default=36)
    parser.add_argument("--pitch-max", type=int, default=96)
    args = parser.parse_args(argv)

    try:
        options = AnalysisOptions(args.target, args.pitch_min, args.pitch_max, args.input_mode)
        with redirect_stdout(StringIO()), TemporaryDirectory(prefix="noteflow-cli-") as folder:
            media = probe(args.source, args.ffprobe)
            result = run_pipeline(media, options, ffmpeg=args.ffmpeg, demucs_python=args.demucs_python,
                                  pitch_python=args.pitch_python, destination=Path(folder) / "stems").analysis
    except ValueError as exc:
        print(json.dumps({"error": {"code": "INVALID_OPTIONS", "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 2
    except NoteFlowError as exc:
        error = {"code": exc.code, "stage": exc.stage, "message": str(exc)}
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    print(json.dumps({
        "media": {"name": args.source.name, "stream_index": result.media.stream_index,
                  "codec": result.media.codec, "duration_s": result.duration_s},
        "notes": [asdict(note) for note in result.notes],
        "options": asdict(result.options),
        "uncertain": [asdict(region) for region in result.uncertain],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] == "--gui":
        from .desktop import main as desktop_main

        raise SystemExit(desktop_main(Path(sys.argv[2]) if len(sys.argv) == 3 else None))
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
