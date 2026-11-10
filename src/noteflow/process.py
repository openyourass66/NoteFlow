"""Run local media tools with a deadline and cooperative cancellation."""

import shutil
import subprocess
from pathlib import Path
from threading import Event
from time import monotonic

from .errors import NoteFlowError


class Cancelled(Exception):
    pass


def check_cancelled(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled


def run_tool(command: str, stage: str, timeout: int, args: tuple[str, ...], cancel: Event | None = None) -> bytes:
    check_cancelled(cancel)
    executable = shutil.which(command)
    if executable is None:
        raise NoteFlowError("TOOL_NOT_FOUND", stage, f"找不到 {Path(command).name}，请在工具设置中检查路径。")
    code = {"render": "SYNTH_FAILED", "separate": "SEPARATION_FAILED"}.get(stage, "DECODE_FAILED")
    try:
        with subprocess.Popen(
            [str(Path(executable).resolve()), *args], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as process:
            deadline = monotonic() + timeout
            try:
                while True:
                    check_cancelled(cancel)
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise NoteFlowError(code, stage, "媒体工具运行超时，请检查文件或重试。")
                    try:
                        output, _ = process.communicate(timeout=min(remaining, 0.2) if cancel else remaining)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            if process.returncode:
                if stage == "separate":
                    raise NoteFlowError(code, stage, "人声分离失败，请检查 Demucs 环境和首次下载模型所需的网络。")
                raise NoteFlowError(code, stage, f"{Path(command).name} 处理失败，请检查输入文件和工具版本。")
    except OSError as exc:
        raise NoteFlowError(code, stage, f"无法运行 {Path(command).name}。") from exc
    check_cancelled(cancel)
    return output
