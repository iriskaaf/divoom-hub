# Python worker bundled without PySide6 or the legacy window.
import os
from pathlib import Path

root = Path(os.environ["DIVOOM_HUB_PYTHON_ROOT"])
source = Path(SPEC).parent
a = Analysis(
    [str(source / "worker.py")],
    pathex=[str(root)],
    datas=[(str(root / "resources" / "fonts"), "resources/fonts")],
    hiddenimports=[
        "keyring.backends.Windows",
        "winrt.windows.media.control",
        "winrt.windows.storage.streams",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
    ],
    excludes=["PySide6", "PyQt5", "PyQt6", "qfluentwidgets", "tkinter", "numpy", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DivoomHub.Backend", icon=str(source.parent / "Assets/icon.ico"),
          console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="DivoomHub.Backend", upx=False)
