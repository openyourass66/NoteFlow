# Windows M0 验证记录

开发机为 Windows 11 x64 家庭版（26200），Intel Core i7-12650H，16 逻辑处理器，15.7 GiB 内存。项目使用独立安装的 CPython 3.11.18 x64。原有 Python 3.12.4 环境无法解析 Basic Pitch 0.4.0 在 Windows 上声明的 `tensorflow<2.15.1` 依赖。

## 开发机结果

2026-11-10 在中文及空格路径下运行 `poc/run.py --qt`。`pip check` 通过。锁定组合包括 PySide6 6.12.0、Basic Pitch 0.4.0、ONNX Runtime 1.31.1、librosa 0.11.0、Mido 1.3.3、NumPy 1.26.4、SciPy 1.17.1、Numba 0.68.1 和 SoundFile 0.14.0（libsndfile 1.2.2）。

在新建的虚拟环境中从 `requirements-win-x64.lock` 复装后，`pip check` 再次通过，两个环境中的模型哈希及共有样本的音符事件完全一致。

| 样本 | 标注音符 | 输出音符 | 50 ms 内同音高匹配 | F1 |
| --- | ---: | ---: | ---: | ---: |
| WAV（PCM） | 12 | 12 | 12 | 1.000 |
| MP3 | 12 | 12 | 12 | 1.000 |
| MP4（AAC） | 12 | 12 | 12 | 1.000 |
| 全零 PCM | 0 | 0 | 0 | — |
| 合成旋律加低音 | 12 | 14 | 12 | 0.923 |
| SF2 合成钢琴独奏 | 12 | 13 | 12 | 0.960 |

三种媒体格式均解码为 22,050 Hz、16 位单声道 PCM。MP4 的视频流在全局索引 0，选中的 AAC 流在索引 1。三个格式的平均匹配起音误差依次为 7.2、4.2 和 7.1 ms。全零 PCM 直接跳过推理。

Basic Pitch 使用本地 `nmp.onnx` 和 `CPUExecutionProvider`。冷启动导入与模型加载约 16.9 秒，首个 10 秒样本的解码和识别约 20.4 秒。三个 30 秒样本热处理耗时分别为 2.14、2.20、2.05 秒，进程峰值工作集为 550.5 MiB。耗时为单台开发机的一次测量。

检查到 SF2 的 bank 0 含 `Grand Piano`（0）、`Nylon Guitar`（24）和 `Violin`（40）。三个预设渲染为非静音、内容不同的 44,100 Hz 双声道 PCM WAV。Qt Multimedia 对三段音频均推进到 278 ms，停止后均恢复到 0 ms 并释放媒体来源。音色可听辨性仍待人工试听。

## 打包结果

PyInstaller 6.22.3 生成约 453 MiB 的 onedir 验证包。在同一台开发机上，将运行时 `PATH` 限制为 Windows 目录后，验证包在中文及空格路径下完成解码、ONNX CPU 推理、三种音色渲染和 Qt 播放停止。共有样本的音符事件与源码运行完全一致。

打包配置保留 librosa 源文件，使 Numba 能在每次运行的输出目录写缓存。构建时将 DLL 搜索路径限制在 Python 和 Windows 目录，避免其他工具的 ICU DLL 影响 Qt。验证包内使用 ONNX CPU，FFmpeg、ffprobe、FluidSynth 和 SF2 通过参数提供。

## 工具和素材

| 项目 | 本地验证版本及来源 | SHA-256 |
| --- | --- | --- |
| FFmpeg、ffprobe | [Gyan Essentials 9.0.2](https://www.gyan.dev/ffmpeg/builds/)，压缩包与上游 SHA-256 一致。构建启用了 `--enable-gpl --enable-version3`。 | `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba` |
| FluidSynth | [2.6.2 Windows x64 cpp11](https://github.com/FluidSynth/fluidsynth/releases/tag/v2.6.2)，压缩包与发布资源 SHA-256 一致。 | `808295345d43c9c428f3fa87d29fbf97a9926f356df95559ff2689f3bd4072d7` |
| GeneralUser GS | [2.0.3 音源及许可证](https://github.com/mrbumpy409/GeneralUser-GS/tree/684543d5e5efaef08d02be50dcda8d552478fa60)，仅用于本地验证。 | `9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe` |
| `nmp.onnx` | [Spotify Basic Pitch 0.4.0](https://github.com/spotify/basic-pitch/tree/v0.4.0) 的 Python wheel 内置模型。 | `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec` |

样本的旋律、MIDI 和音频由 `poc/fixtures.py` 及 `poc/run.py` 生成。每次运行的 JSON 报告含原始音频哈希和起止秒标注。SF2 合成独奏仅作为链路样本。真实独奏与哼唱的质量门槛需要用另行录制或获授权的带标注素材确定。

## M0 退出前的验证

- 在无开发环境的 Windows x64 上断网验证 onedir 包、外部工具发现和 Qt 播放。
- 录制或取得带标注的真实独奏与无伴奏哼唱，分别建立质量基线，并核对混音失败样本。
- 人工试听三个音色，依据实测确定输入限制、节奏建议和近静音门限。
