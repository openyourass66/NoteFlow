import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


poc = Path(SPECPATH)
# Resolve native dependencies from the build environment and Windows, without unrelated tools on PATH.
windows = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(map(str, (Path(sys.executable).parent, windows / "System32", windows)))
package_names = (
    "PySide6", "basic-pitch", "onnxruntime", "librosa", "mido", "numpy",
    "scipy", "numba", "soundfile",
)
datas = collect_data_files("basic_pitch", includes=["saved_models/icassp_2022/nmp.onnx"])
for name in package_names:
    datas += copy_metadata(name)

analysis = Analysis(
    [str(poc / "run.py")],
    pathex=[str(poc)],
    datas=datas,
    # Numba needs real source paths to use NUMBA_CACHE_DIR in a frozen build.
    module_collection_mode={"librosa": "py"},
    excludes=["tensorflow", "IPython", "matplotlib", "pytest"],
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, exclude_binaries=True, name="noteflow-m0", console=True, upx=False)
collection = COLLECT(exe, analysis.binaries, analysis.datas, name="noteflow-m0", upx=False)
