# 第三方组件与外部工具

Windows 目录包基于 `poc/requirements-win-x64.lock` 中的依赖构建。以下记录主要组件及其来源。Qt、CPython 和科学计算 wheel 可能同时包含独立署名的原生组件。

| 组件 | 本地版本 | 上游许可与来源 |
| --- | --- | --- |
| CPython | 3.11.18 | [Python 软件基金会许可](https://docs.python.org/3/license.html) |
| PySide6、Shiboken、Qt Widgets 与 Qt Multimedia | 6.12.0 | [Qt for Python 许可说明](https://doc.qt.io/qtforpython-6/licenses.html) |
| Basic Pitch 与内置 `nmp.onnx` | 0.4.0 | [Basic Pitch 源码与 Apache-2.0 许可](https://github.com/spotify/basic-pitch/tree/v0.4.0)，模型哈希见 [M0 记录](../poc/results.md) |
| ONNX Runtime CPU | 1.31.1 | [MIT 许可](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) |
| librosa、resampy | 0.11.0、0.4.2 | [librosa ISC](https://github.com/librosa/librosa/blob/main/LICENSE.md)、[resampy ISC](https://github.com/bmcfee/resampy/blob/main/LICENSE) |
| Mido、pretty_midi | 1.3.3、0.2.11.post0 | [Mido MIT](https://github.com/mido/mido)、[pretty_midi MIT](https://github.com/craffel/pretty-midi) |
| NumPy、SciPy、Numba、llvmlite | 1.26.4、1.17.1、0.68.1、0.50.0 | [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt)、[SciPy](https://github.com/scipy/scipy/blob/main/LICENSE.txt)、[Numba](https://github.com/numba/numba/blob/main/LICENSE)、[llvmlite](https://github.com/numba/llvmlite/blob/main/LICENSE) |
| SoundFile、libsndfile | 0.14.0、1.2.2 | [SoundFile 及捆绑 libsndfile](https://github.com/bastibe/python-soundfile#license) |
| PyInstaller | 6.22.3 | [引导程序许可与分发例外](https://pyinstaller.org/en/stable/license.html) |

开发机验证使用 FFmpeg 和 ffprobe 9.0.2（Gyan Essentials）、FluidSynth 2.6.2 和 GeneralUser GS 2.0.3。目录包通过路径调用外部工具和音源，这些文件由使用者单独准备。来源、构建选项及哈希见 [M0 记录](../poc/results.md)。

此清单记录本地开发构建。公开分发前需根据实际目录包逐项核对 Qt 模块、原生库、模型资产、许可证文本和对应源码获取方式。

## 可选的本地推理环境

`.tools/inference` 独立于桌面目录包，未把 GPU 运行库和模型复制进安装包。2026-11-13 本地验证的主要版本如下，安装约束见 `packaging/requirements-inference-win.txt`。

| 组件 | 验证版本／模型 | 来源 |
| --- | --- | --- |
| PyTorch、torchaudio | 2.8.0+cu126 | [官方历史版本与安装命令](https://pytorch.org/get-started/previous-versions/)、[PyTorch 许可](https://github.com/pytorch/pytorch/blob/v2.8.0/LICENSE) |
| torchcrepe | 0.0.24、包内 full 权重 | [项目与模型说明](https://github.com/maxrmorrison/torchcrepe)、[MIT 许可](https://github.com/maxrmorrison/torchcrepe/blob/master/LICENSE) |
| Demucs | 4.0.1、htdemucs | [官方模型与推理说明](https://github.com/facebookresearch/demucs)、[MIT 许可](https://github.com/facebookresearch/demucs/blob/main/LICENSE) |

Demucs 权重由其官方加载器首次下载到本地缓存，torchcrepe 权重随 Python 包安装。当前使用这些模型作候选证据，不将单一 F0 轨迹直接视为混音中的主旋律。安装与首次下载需要网络，正常音频推理不使用远程服务。

本地使用的 torchcrepe `full.pth` SHA-256：`133225604dedd2e4005f8bbd1bd0a2ec073ba8b7a6cd31ff6d5edbbfa3539986`。
