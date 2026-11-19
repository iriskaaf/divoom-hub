# PyInstaller spec: one folder (dist\DivoomHub\) with DivoomHub.exe inside.
# A folder build starts instantly; a one-file build unpacks ~100 MB to %TEMP%
# on every launch, which is slow at Windows startup and trips antiviruses.
# Build with build.bat.

a = Analysis(
    ["app.py"],
    datas=[("resources/icon.ico", "resources"), ("resources/icon.png", "resources"),
           ("resources/fonts", "resources/fonts"), ("imgs", "imgs"),
           ("resources/illustrations", "resources/illustrations")],
    hiddenimports=["keyring.backends.Windows", "winrt.windows.media.control",
                   "winrt.windows.storage.streams", "winrt.windows.foundation",
                   "winrt.windows.foundation.collections"],
    excludes=["tkinter", "unittest", "pytest", "pydoc", "PIL.ImageTk", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf", "numpy"],
    noarchive=False,
)
# Qt parts the app never uses (checked with the DLL import tables, 2026-10-19):
# the virtual-keyboard plugin alone drags in Quick, QML and OpenGL, the PDF image
# plugin drags in Qt6Pdf, opengl32sw is a 20 MB software OpenGL for Quick, the TLS
# and network-information plugins serve QtNetwork features we do not use (only
# QLocalSocket for the single instance). About 45 MB less to ship and to load.
UNUSED_QT = (
    "opengl32sw.dll", "qt6quick", "qt6qml", "qt6opengl", "qt6pdf", "qt6virtualkeyboard",
    "plugins/platforminputcontexts/", "plugins/imageformats/qpdf", "plugins/imageformats/qtiff",
    "plugins/imageformats/qwebp", "plugins/imageformats/qicns", "plugins/imageformats/qtga",
    "plugins/imageformats/qwbmp", "plugins/tls/", "plugins/networkinformation/",
    "plugins/generic/", "plugins/platforms/qdirect2d", "plugins/platforms/qminimal",
)


def wanted(entry) -> bool:
    name = entry[0].replace("\\", "/").lower()
    # Qt 6.11 imports the Windows ICU ABI (unversioned ucnv_* exports).
    # A Poppler/Conda icuuc.dll on the build PATH exports *_78 instead;
    # bundling it makes QtWidgets fail with ERROR_PROC_NOT_FOUND (127).
    # Resolve this OS dependency from System32, never from build tooling.
    if name.rsplit("/", 1)[-1] in ("icuuc.dll", "icudt78.dll"):
        return False
    if not name.startswith("pyside6/"):
        return True
    if name.startswith("pyside6/translations/"):
        return name.rsplit("/", 1)[-1].startswith("qtbase_ru")  # Russian texts of standard dialogs
    return not any(part in name for part in UNUSED_QT)


a.binaries = [e for e in a.binaries if wanted(e)]
a.datas = [e for e in a.datas if wanted(e)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DivoomHub",
    console=False,
    icon="resources/icon.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DivoomHub", upx=False)
