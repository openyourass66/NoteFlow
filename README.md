# NoteFlow

NoteFlow 是面向 Windows x64 的本地制谱工具。它从音频或视频中提取主旋律并生成数字简谱，支持逐音编辑、原曲对照试听、项目保存，以及 TXT、MIDI 和 WAV 导出。

## 安装与启动

准备 Python 3.11 x64。在项目根目录打开 PowerShell，创建虚拟环境并启动桌面版。

```powershell
py -3.11 -m venv .venv
$nfPython = '.\.venv\Scripts\python.exe'
& $nfPython -m pip install -c .\poc\requirements-win-x64.lock -e '.[desktop]'
& $nfPython -m noteflow
```

| 功能 | 需准备的工具 |
| --- | --- |
| 导入、解码和识别 | FFmpeg 与 ffprobe |
| 合成旋律或简谱的试听和 WAV 导出 | FluidSynth 与 GM SoundFont（`.sf2`） |
| 分离人声与伴奏 | 安装了 Demucs 的独立 Python 环境 |

桌面版会查找项目根目录下的 `.tools`，也可从 `PATH` 查找 FFmpeg、ffprobe 和 FluidSynth，或在右上角「⋯ → 工具设置」指定工具和音源路径。可将 `.sf2` 直接放入 `.tools`。工具来源见 [第三方组件与外部工具](docs/third-party.md)。

已有目录包时，双击 `dist\NoteFlow\NoteFlow.exe`，保留同目录的 `_internal`。将目录包移出项目后，可把外部工具和音源放到 `NoteFlow.exe` 旁的 `tools` 文件夹。自行构建目录包见下方的「开发与打包」。

## 桌面工作台

1. **导入媒体**。点击启动页的「导入媒体」、工作区左上角的导入图标，或将文件拖入窗口。支持 PCM WAV、MP3 和含 AAC 音轨的 MP4 / M4A。处理首条音轨，单文件最大 200 MB，音轨最长 120 秒。
2. **生成简谱**。默认使用「自动」。已配置 Demucs 时，检测到较多重叠音会尝试分离人声，优先采用有足够旋律且重叠更少的人声轨。清唱或独奏可直接选择「原曲 / 独奏」。也可手动点击「分离人声与伴奏」，再选择「分离人声」。人声简谱使用原曲的拍点，并用 pYIN 复核人声旋律的八度。
3. **校准和编辑**。在谱面上方展开「节奏与调号」，修改 BPM、首拍偏移或主音后应用。切换到「音符编辑」，双击单元格可调整音符起止时间、MIDI 音高和力度，也可添加、删除音符或升降半音和八度。音符编辑和节奏校准支持撤销与重做。
4. **对照试听**。点击底部的音轨开始播放。选用钢琴、尼龙吉他或小提琴后，「旋律」按识别音符的起止时间播放，「简谱」按量化后的谱面节奏播放。播放时可暂停、拖动进度、调整音量和 0.5–1.5 倍速，也可点击谱面音符定位。
5. **保存或导出**。工作区左上角的保存图标生成 `.noteflow` 文件，保存解码后的原曲、已有分轨、识别结果、手工修正、谱面设置和音色。可从启动页「打开项目」或「最近项目」恢复，无需原始媒体。工作区也提供打开项目的文件夹图标和「⋯ → 最近项目」。「导出」菜单可生成 UTF-8 TXT、MIDI，以及已有分轨或合成音轨的 WAV。

简谱采用固定 4/4 拍和恒定速度，适合清晰的单声部旋律。混音分离后的人声轨可能仍含和声或伴奏残留。

| 操作 | 快捷键 |
| --- | --- |
| 导入媒体 / 打开项目 | `Ctrl+O` / `Ctrl+Shift+O` |
| 保存项目 / 另存为 | `Ctrl+S` / `Ctrl+Shift+S` |
| 生成简谱 / 取消任务 | `Ctrl+G` / `Esc` |
| 切换简谱与音符编辑 | `Ctrl+Tab` |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Y` |

「⋯ → 使用说明」可查看工作台内的操作提示。取消识别时，程序会等待当前推理结束。

### 安装可选的人声分离环境

Windows 上使用独立的 Python 3.11 x64 环境安装 Demucs，桌面程序会自动查找项目的 `.tools\demucs`。已有 `.venv-m0` 时，也可以用其中的 Python 代替下方的 `py -3.11`。

```powershell
py -3.11 -m venv .tools\demucs
$nfDemucsPython = '.\.tools\demucs\Scripts\python.exe'
& $nfDemucsPython -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
& $nfDemucsPython -m pip install demucs==4.0.1 soundfile==0.14.0 numpy==1.26.4
```

首次分离会联网下载约 84 MB 的 HT Demucs 模型权重。推理在本地 CPU 上运行。环境安装在其他位置时，在「工具设置」的「Demucs Python」一栏选择该环境的 `python.exe`。

## 命令行识别

使用安装步骤中的 `$nfPython`，将示例中的媒体和工具路径替换为实际位置。FFmpeg 和 ffprobe 已在 `PATH` 上时，可省略两个工具参数。

```powershell
& $nfPython -m noteflow 'C:\Music\旋律.mp4' `
    --ffmpeg 'C:\tools\ffmpeg\bin\ffmpeg.exe' `
    --ffprobe 'C:\tools\ffmpeg\bin\ffprobe.exe'
```

只使用命令行时，安装命令可用 `-e .` 省去桌面依赖。

标准输出为 UTF-8 JSON，包含音轨索引、实际解码时长和候选音符。音符含起止秒数、MIDI 音高、模型幅值和力度。添加 `--demucs-python $nfDemucsPython` 可先分离人声，再输出经八度复核的人声候选音符。

## 开发与打包

将 FFmpeg 和 ffprobe 加入 `PATH` 后，在项目根目录运行测试。打包使用同一份 Windows 依赖锁文件约束 PyInstaller 的版本。

```powershell
& $nfPython -m pip install -c .\poc\requirements-win-x64.lock -e '.[desktop,test]' pyinstaller
& $nfPython -m pytest
& $nfPython -m PyInstaller --noconfirm .\packaging\noteflow.spec
```

构建输出在 `dist\NoteFlow`。将测试或试听生成的个人媒体、项目与导出文件保存在工作区外，或使用项目根目录下已被忽略的 `.poc-output`。历史测试结果见 [Windows 验收记录](docs/acceptance.md)。

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
