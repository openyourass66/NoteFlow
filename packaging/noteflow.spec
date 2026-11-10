import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


directory = Path(SPECPATH)
windows = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(map(str, (Path(sys.executable).parent, windows / "System32", windows)))

analysis = Analysis(
    [str(directory / "launch.py")],
    pathex=[str(directory.parent / "src")],
    datas=collect_data_files("basic_pitch", includes=["saved_models/icassp_2022/nmp.onnx"]),
    module_collection_mode={"librosa": "py"},
    excludes=["tensorflow", "IPython", "matplotlib", "pytest"],
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, exclude_binaries=True, name="NoteFlow", console=False, upx=False)
collection = COLLECT(exe, analysis.binaries, analysis.datas, name="NoteFlow", upx=False)
