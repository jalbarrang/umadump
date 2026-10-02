# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: umadump Dear PyGui front-end as a portable onedir bundle.

Build with the helper (recommended)::

    python app/build.py

or directly::

    python -m PyInstaller --noconfirm --clean app/umadump-gui.spec
"""
from pathlib import Path

# SPECPATH is the directory containing this spec file (app/).
ROOT = Path(SPECPATH).resolve().parent
ENTRY = ROOT / "app" / "app.py"
NAME = "umadump-gui"

# Stdlib extras and the previous Qt toolkit. Nothing imports these any more, so
# they should never be collected; listing them keeps a stale requirement from
# silently bloating the bundle.
EXCLUDES = [
    "PySide6", "shiboken6",
    # Optional heavy third-party / stdlib packages that occasionally get pulled in.
    "tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    # Vendored UI/monospace fonts; the license texts ride along in the same folder.
    datas=[(str(ROOT / "app" / "fonts"), "app/fonts")],
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
