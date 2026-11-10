# NoteFlow

NoteFlow 面向 Windows，将本地单声部旋律转换为数字简谱，并用选定的乐器音色试听。

## 启动桌面版

打开 `dist\NoteFlow\NoteFlow.exe`，并保留同目录的 `_internal`。首次运行可在「工具设置」填写 FFmpeg、ffprobe、FluidSynth 和本地 GM SoundFont（`.sf2`）的路径。FFmpeg 与 ffprobe 可从 `PATH` 查找。FluidSynth 和 SF2 用于试听。

在已准备好 `.venv-m0` 和 `.tools` 的开发目录，可直接运行 `& .\.venv-m0\Scripts\python.exe -m noteflow`。源码启动会查找项目 `.tools` 中的本地工具。新环境使用 Python 3.11 x64，运行 `python -m pip install -c .\poc\requirements-win-x64.lock -e '.[desktop]'` 后用 `python -m noteflow` 启动。

1. 打开或拖入 PCM WAV、MP3 或含 AAC 音轨的 MP4，然后点击「生成简谱」。
2. 查看谱面，需要时修改 BPM、首拍偏移或主音，再点击「应用校准」。
3. 选择钢琴、尼龙吉他或小提琴进行试听，或导出 UTF-8 TXT 和 MIDI。

首版适合清晰的单声部旋律，采用固定 4/4 拍和恒定速度。单文件上限为 200 MB，首条音轨上限为 120 秒。长时间识别时可取消，取消会等当前推理返回再释放工作目录。

## 识别自己的文件

命令行入口沿用同一套探测、解码和 ONNX CPU 识别流程，输出秒级音符 JSON。

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

标准输出为 UTF-8 JSON，包含音轨索引、实际解码时长和原始候选音符。音符含起止秒数、MIDI 音高、模型幅值和力度。

## 开发与打包

媒体探测、识别、节奏和制谱使用普通函数与数据类。Qt 窗口一次运行一个后台任务。制谱、试听与导出共用同一份 `Score`，校准复用识别结果。

完整回归需安装 `.[desktop,test]`，将 FFmpeg 和 ffprobe 加入 `PATH` 后运行 `python -m pytest`。本机有 FluidSynth、SF2 和音频输出设备时，桌面回归也会验证三种音色的播放与停止。

```powershell
& .\.venv-m0\Scripts\python.exe -m PyInstaller --noconfirm .\packaging\noteflow.spec
```

[第三方组件与外部工具](docs/third-party.md) · [验收记录](docs/acceptance.md)

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

### 构建 M0 验证包

```powershell
& $nfPython -m PyInstaller --noconfirm .\poc\noteflow-m0.spec
& .\dist\noteflow-m0\noteflow-m0.exe @nfArgs
```

保留 `dist\noteflow-m0` 下的完整目录。运行时通过参数提供 FFmpeg、ffprobe、FluidSynth 和 SF2。
