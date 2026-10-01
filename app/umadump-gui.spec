# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: umadump Qt front-end as a portable onedir bundle.

Build with the helper (recommended)::

    python app/build.py

or directly::

    python -m PyInstaller --noconfirm --clean app/umadump-gui.spec
"""
from pathlib import Path
import sys

# SPECPATH is the directory containing this spec file (app/).
ROOT = Path(SPECPATH).resolve().parent
ENTRY = ROOT / "app" / "app.py"
NAME = "umadump-gui"

# Qt add-ons and stdlib extras the GUI never imports. Excluding them keeps the
# bundle small; they are pure-Python modules, so the underlying Qt DLLs still
# ship if something genuinely depends on them.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtSerialBus",
    # Optional heavy third-party / stdlib packages that occasionally get pulled in.
    "tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)

# On macOS PyInstaller additionally wraps the collected files into a .app bundle.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=None,
        bundle_identifier="com.umadump.gui",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSRequiresAquaSystemAppearance": False,
        },
    )
