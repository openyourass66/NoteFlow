"""Prepare known-melody review cases; --send explicitly invokes six API calls."""

import argparse
import json
import os
from pathlib import Path
from tempfile import mkdtemp

from noteflow.desktop_settings import _default_tools
from noteflow.review_calibration import check_reviewer
from noteflow.review_cloud import CloudConfig, DEFAULT_MODEL, PROTOCOLS, environment_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".poc-output/audio-review-calibration"))
    parser.add_argument("--base-url", default=os.environ.get("NOTEFLOW_REVIEW_BASE_URL", ""))
    parser.add_argument("--model", default=os.environ.get("NOTEFLOW_REVIEW_MODEL", DEFAULT_MODEL))
    parser.add_argument("--protocol", choices=PROTOCOLS, default="auto")
    parser.add_argument("--send", action="store_true", help="上传合成测试音频，最多6次付费请求；默认只本地准备")
    args = parser.parse_args()
    url = args.base_url.strip().rstrip("/")
    key = os.environ.get("NOTEFLOW_REVIEW_API_KEY") or environment_key(url)
    config = CloudConfig(url, args.model, key, args.protocol)
    if args.send:
        try:
            config.validate()
        except ValueError as error:
            parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="check-", dir=args.output))
    report = check_reviewer(_default_tools(), config, folder, send=args.send, progress=print)
    print(json.dumps({"status": report["status"], "calls": report["calls"], "report": str(folder / "calibration.json")}, ensure_ascii=False))
    return 0 if report["status"] in ("prepared", "passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
