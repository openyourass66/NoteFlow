# NoteFlow

NoteFlow 是 Windows 本地制谱工作台，支持音频导入、人声分离、旋律识别、数字简谱、音符编辑和项目保存。

## 启动桌面版

打开 `dist\NoteFlow\NoteFlow.exe`，并保留同目录的 `_internal`。在本项目内运行时，程序会自动查找 `.tools` 里的工具和音源。移到其他位置时，可把工具放在程序旁的 `tools` 文件夹、将可执行文件加入 `PATH`，或在「工具设置」中指定路径。FluidSynth 和本地 GM SoundFont（`.sf2`）用于试听。

在已准备好 `.venv-m0` 和 `.tools` 的开发目录，可直接运行 `& .\.venv-m0\Scripts\python.exe -m noteflow`。源码启动会查找项目 `.tools` 中的本地工具。新环境使用 Python 3.11 x64，运行 `python -m pip install -c .\poc\requirements-win-x64.lock -e '.[desktop]'` 后用 `python -m noteflow` 启动。

1. 打开或拖入 PCM WAV、MP3 或含 AAC 音轨的 MP4 / M4A。导入后可点击「播放原曲」听首条音轨。清唱或独奏可直接点「生成简谱」。歌曲混音可先点「分离人声与伴奏」，分别播放两条音轨，再从人声生成简谱。扩展名误标为 `.mp3` 的 M4A 可直接导入。
2. 查看谱面，需要时修改 BPM、首拍偏移或主音，再点击「应用校准」。
3. 选择钢琴、尼龙吉他或小提琴。「试听旋律」保留识别音符的起止时间，「播放简谱」按谱面节奏播放。可导出当前简谱的 UTF-8 TXT 和 MIDI。

简谱采用固定 4/4 拍和恒定速度。单文件上限为 200 MB，首条音轨上限为 120 秒。分离后从原曲估计拍点，从人声识别音符，并用 pYIN 的基频轨迹复核八度。人声轨可能同时包含和声及少量伴奏残留。分轨随当前导入保留，换曲或关闭窗口时清理。识别期间取消会等待当前推理结束。

### 安装可选的人声分离环境

Windows 上使用独立的 Python 3.11 x64 环境安装 Demucs，桌面程序会自动查找项目的 `.tools\demucs`。已有 `.venv-m0` 时，也可以用其中的 Python 代替下方的 `py -3.11`。

```powershell
py -3.11 -m venv .tools\demucs
$nfDemucsPython = '.\.tools\demucs\Scripts\python.exe'
& $nfDemucsPython -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
& $nfDemucsPython -m pip install demucs==4.0.1 soundfile==0.14.0 numpy==1.26.4
```

首次分离会联网下载约 84 MB 的 HT Demucs 模型权重。推理在本地 CPU 上运行。环境安装在其他位置时，在「工具设置」的「Demucs Python」一栏选择该环境的 `python.exe`。

## 桌面工作台

- 左侧导入音频或打开项目，可从最近项目继续工作。选择「识别来源」后生成简谱。
- 「音符编辑」页可双击修改起止秒数、MIDI 音高和力度，也可添加、删除音符或调整半音、八度。时间调整会检查音轨边界和音符重叠。撤销和重做覆盖音符修改及节奏校准。
- 播放区支持原曲、人声、伴奏、旋律和简谱的对照试听，以及暂停、定位、0.5–1.5 倍速和音量调整。播放时谱面高亮当前音符，点击谱面音符可定位。
- 「保存项目」生成 `.noteflow` 文件，包含解码后的原曲、已有分轨、识别候选音符、手工修正、速度、调号和音色。项目可离线重新打开，原始媒体移动后仍可恢复。换曲和关闭窗口会提示保存未保存内容。
- 可导出 TXT、MIDI，以及人声、伴奏、合成旋律或简谱的 WAV 音频。音频合成使用工具设置中的 FluidSynth 和 SoundFont。

快捷键为 Ctrl+O 导入音频、Ctrl+Shift+O 打开项目、Ctrl+S 保存、Ctrl+Shift+S 另存为、Ctrl+Z 撤销、Ctrl+Y 重做。菜单「帮助 → 使用说明」提供操作提示。

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

标准输出为 UTF-8 JSON，包含音轨索引、实际解码时长和候选音符。音符含起止秒数、MIDI 音高、模型幅值和力度。添加 `--demucs-python $nfDemucsPython` 可先分离人声，再输出经八度复核的人声候选音符。

## 开发与打包

媒体探测、识别、节奏和制谱使用普通函数与数据类。Qt 窗口一次运行一个后台任务。`Score` 同时保留按时间筛出的旋律和量化后的谱面，校准复用识别结果。

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
