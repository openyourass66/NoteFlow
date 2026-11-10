# NoteFlow

NoteFlow 面向 Windows，将本地单声部旋律转换为数字简谱，并用选定的乐器音色试听。

M1 命令行可以识别本地 PCM WAV、MP3 或含 AAC 音轨的 MP4，输出秒级音符 JSON。媒体处理、音高识别和命令行入口各自独立，由 `noteflow.analysis.analyze()` 串联。分析使用 FFmpeg、ffprobe 和本地 ONNX CPU 模型。

## 识别自己的文件

在项目根目录运行以下 PowerShell 命令。已有 `.venv-m0` 时可复用其中的依赖。将媒体路径和工具目录改成实际位置。

```powershell
$nfPython = '.\.venv-m0\Scripts\python.exe'
& $nfPython -m pip install --no-deps --no-build-isolation -e .

$nfFfmpeg = '.\.tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin'
& $nfPython -m noteflow 'D:\Music\旋律.mp4' `
    --ffmpeg (Join-Path $nfFfmpeg 'ffmpeg.exe') `
    --ffprobe (Join-Path $nfFfmpeg 'ffprobe.exe')
```

新环境使用 Python 3.11 x64，创建虚拟环境后运行 `python -m pip install -c .\poc\requirements-win-x64.lock -e .`。该命令用 M0 的版本锁约束 CLI 所需依赖。如果 FFmpeg 和 ffprobe 已在 `PATH` 上，可以省略两个工具路径参数。

单文件上限为 200 MB，首条音轨上限为 120 秒。标准输出为 UTF-8 JSON，包含音轨索引、实际解码时长和音符。音符含起止秒数、MIDI 音高、模型幅值和力度。量化和单声部规整安排在 M2。

开发时安装 `.[test]`，确保 FFmpeg 和 ffprobe 在 `PATH` 上，然后运行 `python -m pytest`。

## 运行 M0

M0 独立脚本用带标注的合成样本验证三种输入、ONNX CPU 识别、音色渲染和 Qt 播放。环境、实测结果和待验证项目见 [Windows M0 验证记录](poc/results.md)。

使用 Windows x64、Python 3.11 x64、FFmpeg、ffprobe、FluidSynth 和本地 GM SoundFont（SF2）。在项目根目录运行以下 PowerShell 命令。已有 `.venv-m0` 时可直接设置 `$nfPython`。将工具路径替换成实际安装位置。

```powershell
py -3.11 -m venv .venv-m0
$nfPython = '.\.venv-m0\Scripts\python.exe'
& $nfPython -m pip install --only-binary=:all: -r .\poc\requirements-win-x64.lock
& $nfPython -m pip check

$nfArgs = @(
    '--ffmpeg', 'C:\tools\ffmpeg\bin\ffmpeg.exe',
    '--ffprobe', 'C:\tools\ffmpeg\bin\ffprobe.exe',
    '--fluidsynth', 'C:\tools\fluidsynth\bin\fluidsynth.exe',
    '--sf2', 'C:\soundfonts\GeneralUser-GS.sf2',
    '--output', '.\.poc-output\中文 路径',
    '--qt'
)
& $nfPython .\poc\run.py @nfArgs
```

每次运行在输出目录下创建一个独立的 `m0-*` 子目录，其中的 `report.json` 记录样本哈希、识别事件、精确率与召回率、F1、耗时和进程峰值工作集。移除 `--qt` 可在没有音频设备的环境中运行解码、识别和渲染验证。用 `--hot-runs 0` 可跳过三个 30 秒的性能样本。

如需加入自录或获授权的音频，传入 `--recordings` 和 JSON 清单路径。`file` 相对于清单目录，`category` 为 `solo`、`humming` 或 `mix`，每条 `notes` 依次填写相对于音频起点的起止秒数和 MIDI 音高。

```json
[
  {"file": "humming.wav", "category": "humming", "notes": [[0.0, 0.5, 60], [0.75, 1.25, 62]]}
]
```

## 构建最小验证包

```powershell
& $nfPython -m PyInstaller --noconfirm .\poc\noteflow-m0.spec
& .\dist\noteflow-m0\noteflow-m0.exe @nfArgs
```

保留 `dist\noteflow-m0` 下的完整目录。运行时通过参数提供 FFmpeg、ffprobe、FluidSynth 和 SF2。
