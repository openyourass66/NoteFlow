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
| 内置乐器演奏和 WAV 导出 | FluidSynth 与 GM SoundFont（`.sf2`） |
| 音频分轨、神经网络音高复核 | 可选的独立推理环境，支持 NVIDIA CUDA |

桌面版会查找项目根目录下的 `.tools`，也可从 `PATH` 查找 FFmpeg、ffprobe 和 FluidSynth，或在右上角「⋯ → 工具设置」指定工具和音源路径。可将 `.sf2` 直接放入 `.tools`。工具来源见 [第三方组件与外部工具](docs/third-party.md)。

已有目录包时，双击 `dist\NoteFlow\NoteFlow.exe`，保留同目录的 `_internal`。将目录包移出项目后，可把外部工具和音源放到 `NoteFlow.exe` 旁的 `tools` 文件夹。自行构建目录包见下方的「开发与打包」。

## 桌面工作台

1. **导入并识别分轨**。点击启动页的「导入媒体」、工作区左上角的导入图标，或将文件拖入窗口。支持 PCM WAV、MP3 和含 AAC 音轨的 MP4 / M4A。已有多条可用音轨的文件直接列出音轨。单轨文件在配置了 Demucs 后自动拆分为人声、贝斯、鼓和其他乐器，另提供合成伴奏。单文件最大 1 GB，音轨最长 120 秒。
2. **选轨并生成**。从「选择音轨」中选一条，可先点「试听选轨」，再点「生成简谱」。识别混合伴奏时，软件会参考已有的贝斯和其他乐器轨，减少把背景低音写进主旋律。清唱、独奏、未配置 Demucs，或分轨取消及失败后，可以选择原曲。选模型分轨时，拍点仍从原曲估计。旋律处在较高或较低音域时，可以切换音域后重新生成。模型证据偏弱的音符在编辑页标为「待复核」。
3. **校准和编辑**。在谱面上方展开「节奏与调号」，修改 BPM、首拍偏移或主音后应用。切换到「音符编辑」，双击单元格可调整音符起止时间、MIDI 音高和力度，也可添加、删除音符或升降半音和八度。音符编辑和节奏校准支持撤销与重做。
4. **对照试听**。新导入的媒体默认使用「自动」。点击「演奏」时，从生成简谱所用的音轨匹配最接近的音色。可以手动选择内置的古筝，或当前 SoundFont 提供的钢琴、吉他、贝斯、弦乐、铜管、木管等 27 种 GM 音色。匹配证据不足时使用默认可用音色。演奏保留识别或编辑后的起止时间，切换音轨时保留播放位置。支持暂停、拖动进度、音量、0.5–1.5 倍速和点击谱面定位。
5. **保存或导出**。工作区左上角的保存图标生成 `.noteflow` 文件，保存解码后的音轨、选轨、识别结果、手工修正、谱面设置和音色。可从启动页「打开项目」或「最近项目」恢复，无需原始媒体。新版可打开旧版项目。工作区也提供打开项目的文件夹图标和「⋯ → 最近项目」。「导出」菜单可生成 UTF-8 TXT、MIDI，以及已有分轨或合成音轨的 WAV。

演奏 WAV 导出保留所选音色。MIDI 导出记录音符和预设编号，在其他软件中播放古筝 MIDI 时可加载本包的 `guzheng.sf2`（音色库 0、程序编号 107，从 0 计数）。

简谱目前采用固定 4/4 拍、恒定速度和十六分音符网格；三连音和自由速度还不能准确排版，但不会把演奏强制吸附到网格。人声轨可能含和声，其他乐器轨可能含多件乐器，复杂混音仍需试听复核。导入、分轨、识别与音色匹配在本地完成。

| 操作 | 快捷键 |
| --- | --- |
| 导入媒体 / 打开项目 | `Ctrl+O` / `Ctrl+Shift+O` |
| 保存项目 / 另存为 | `Ctrl+S` / `Ctrl+Shift+S` |
| 生成简谱 / 取消任务 | `Ctrl+G` / `Esc` |
| 切换简谱与音符编辑 | `Ctrl+Tab` |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Y` |

「⋯ → 使用说明」可查看操作提示。Basic Pitch 按窗口检查取消；分离和神经音高复核通过独立进程运行，取消时终止该任务。未安装神经音高环境时，部分单声部使用 pYIN 复核，它需等待当前调用结束。

### 安装可选的本地 GPU 推理环境

Windows 上使用独立的 Python 3.11 x64 环境，避免把 PyTorch 和 CUDA 打入桌面主程序。桌面程序自动查找 `.tools\inference`，GPU 可用时使用 CUDA，否则使用 CPU。已在 RTX 4060 Laptop 8 GB 上验证以下组合：

```powershell
py -3.11 -m venv .tools\inference
$nfInference = '.\.tools\inference\Scripts\python.exe'
& $nfInference -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu126
& $nfInference -m pip install -r .\packaging\requirements-inference-win.txt
& $nfInference -m pip check
& $nfInference -c 'import torch; print(torch.cuda.is_available())'
```

没有 NVIDIA GPU 时，将安装索引末尾的 `cu126` 改成 `cpu`。首次分离会下载 HT Demucs 权重；torchcrepe 使用包内的 full 权重。准备完成后，音频在本地处理，不上传。环境安装在其他位置时，在「工具设置」中把「分离环境 Python」和「音高复核 Python」指向该环境。清空后者可停用神经音高复核；分离仍兼容旧的 `.tools\demucs` 环境。依赖及模型来源见 [第三方组件](docs/third-party.md)。

## 可选的云端音频复核（实验功能）

生成或打开乐谱后，点击播放器旁的「音频复核…」。它会比较原曲与固定钢琴演奏，检查主旋律的音高、八度、节奏和连贯性。本地模型根据音频证据提出局部修改，云端再比较修改前后，最多循环 3 轮。

1. 在「⋯ → 云端模型设置…」填写 **HTTPS Base URL、模型名和 API Key**，保存时无需上传音频。服务需提供支持 WAV 音频输入和文本输出的 Chat Completions 接口。Base URL 也可填写完整的 `/chat/completions` 地址。「自动」按地址识别百炼并选择 Data URI，其他服务使用普通 Base64，也可为网关手动指定格式。百炼默认模型为 `qwen3.8-omni-flash`。接口说明见 [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) 和 [百炼 Qwen-Omni](https://help.aliyun.com/zh/model-studio/qwen-omni)。
2. 建议先点击「检查复核能力（6 次）」。仅上传内置旋律，检查正确演奏、错音高、错八度、断奏与交换顺序对照。不修改当前乐谱；检查通过也不代表实际歌曲准确。
3. 选择复核范围，默认前 20 秒；可选整段。设置轮数和请求上限，点击「上传并开始复核」才会发送原曲及演奏音频。默认最多 24 次请求，失败不自动重试；这是调用次数限制，并非金额上限。
4. 自动修正仍需在交换顺序的两次对照中都获支持才采用。停止时保留此前已采用的版本，以及尚未采纳的候选。
5. 结果窗口默认选中第一个候选。直接点击「原曲」「修改前」或「候选」试听，满意后点「应用到简谱」。Ctrl+Z 撤销，Ctrl+S 保存。没有候选时可点击「生成候选」，在本地重建疑点片段。「查看详情」可定位音符或导出记录。

服务地址、模型名和接口格式保存在本机。API Key 由 Windows 按当前用户加密，重启后自动填入，也可清空并保存以移除。首次设置可用 `NOTEFLOW_REVIEW_BASE_URL`、`NOTEFLOW_REVIEW_MODEL` 和 `NOTEFLOW_REVIEW_API_KEY` 预填，百炼也可用 `DASHSCOPE_API_KEY`。项目和复核报告只包含业务数据。

当前乐谱的复核结果保存在内存中。关闭结果窗口后，再次点「音频复核…」会打开上次的疑点和候选。想再次请求云端时用「重新复核…」。退出软件或切换项目时清空结果。乐谱变动后可查看旧疑点，应用候选前需按当前乐谱重新生成。

「查看详情」可手动导出 JSON。「⋯ → 导入复核记录…」可在对应乐谱上恢复反馈，候选从当前音频重新生成。手动导出的记录仅含音符、反馈及用量等报告数据。

本地修正包括音高／起音微调和疑点乐句重建。重建可补入有音频支持的漏音、拆分或合并音符，保留选区外音符；声部错误仍需人工选择。**手动应用不表示云端复核通过，“云端复核通过”也不是音准准确率。** 已观察到 Qwen 的漏报及时间判断错误，仍需人工试听。实现与验证边界见 [音频复核循环说明](docs/音频复核循环说明.md)。

开发者可仅在本地生成受控检查素材：

```powershell
& $nfPython .\poc\check_audio_reviewer.py
```

配置上述环境变量后，加 `--send` 会上传合成测试音频并执行最多 6 次付费请求。没有 `--send` 时不会访问云端。每次输出到独立的 `.poc-output/audio-review-calibration/check-*` 目录。

## 命令行识别

使用安装步骤中的 `$nfPython`，将示例中的媒体和工具路径替换为实际位置。FFmpeg 和 ffprobe 已在 `PATH` 上时，可省略两个工具参数。

```powershell
& $nfPython -m noteflow 'C:\Music\旋律.mp4' `
    --ffmpeg 'C:\tools\ffmpeg\bin\ffmpeg.exe' `
    --ffprobe 'C:\tools\ffmpeg\bin\ffprobe.exe' `
    --target instrument --pitch-python $nfInference
```

只使用命令行时，安装命令可用 `-e .` 省去桌面依赖。

命令行读取文件的首条音轨，与桌面共用主旋律识别流程。标准输出为 UTF-8 JSON，包含音轨索引、实际解码时长、主旋律音符、提取设置和待复核区间。音符含起止秒数、MIDI 音高、模型幅值和力度。人声用 `--target vocal --demucs-python $nfInference`；清唱可加 `--source original`。限定音域用 `--pitch-min 60 --pitch-max 96`。未指定 `--pitch-python` 时不启用神经音高复核。

## 开发与打包

将 FFmpeg 和 ffprobe 加入 `PATH` 后，在项目根目录运行测试。打包使用同一份 Windows 依赖锁文件约束 PyInstaller 的版本。

```powershell
& $nfPython -m pip install -c .\poc\requirements-win-x64.lock -e '.[desktop,test]' pyinstaller
& $nfPython -m pytest
& $nfPython -m PyInstaller --noconfirm .\packaging\noteflow.spec
```

构建输出在 `dist\NoteFlow`。将测试或试听生成的个人媒体、项目与导出文件保存在工作区外，或使用项目根目录下已被忽略的 `.poc-output`。历史测试结果见 [Windows 验收记录](docs/acceptance.md)。

可用 `--distpath dist/rebuild --workpath build/rebuild` 将目录包单独输出。旧 `.noteflow` 项目可读取，新保存格式为版本 3。历史重构内容与实测边界见 [本地重构验证记录](docs/本地重构验证记录.md)。

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
