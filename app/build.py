#!/usr/bin/env python3
"""Build a portable umadump-gui bundle for the current OS with PyInstaller.

PyInstaller cannot cross-compile, so run this on each target OS (Windows, Linux).
Outputs land in ``app/dist/``:

  * ``app/dist/umadump-gui/``               — runnable onedir bundle
  * ``app/dist/umadump-gui-<ver>-<os>.zip`` — Windows archive (or ``.tar.gz`` on Linux)

Usage::

    python app/build.py                 # build + archive
    python app/build.py --no-archive    # build only
"""
from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
SPEC = APP_DIR / "umadump-gui.spec"
NAME = "umadump-gui"
DIST_DIR = APP_DIR / "dist"
WORK_DIR = APP_DIR / "build"

_MACHINE_ALIASES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}


def project_version() -> str:
    """Read CURRENT_VERSION from update_check.py without importing the package."""
    text = (ROOT / "update_check.py").read_text(encoding="utf-8")
    match = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "0.0.0"


def platform_tag() -> str:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(
        platform.system(), platform.system().lower()
    )
    machine = _MACHINE_ALIASES.get(platform.machine().lower(), platform.machine().lower())
    return f"{system}-{machine}"


def make_archive(bundle: Path, out: Path) -> None:
    if platform.system() == "Windows":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(bundle.parent))
    else:
        # tar.gz preserves the executable bit on Linux.
        with tarfile.open(out, "w:gz") as tf:
            tf.add(bundle, arcname=bundle.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the umadump-gui bundle for this platform.")
    parser.add_argument("--no-archive", action="store_true", help="Skip creating the archive.")
    parser.add_argument("--keep-build", action="store_true",
                        help="Keep app/build/ (intermediate files; useful only for debugging).")
    args = parser.parse_args()

    if platform.system() == "Darwin":
        print(
            "error: macOS is not supported — the live memory backend has no macOS "
            "implementation and the umadump core does not import cleanly there.",
            file=sys.stderr,
        )
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "error: PyInstaller is not installed for this interpreter.\n"
            "       Install build deps with: pip install -r app/requirements-build.txt",
            file=sys.stderr,
        )
        return 2

    if not SPEC.is_file():
        print(f"error: spec file not found: {SPEC}", file=sys.stderr)
        return 2

    for stale in (DIST_DIR, WORK_DIR):
        if stale.exists():
            shutil.rmtree(stale)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(DIST_DIR),
        "--workpath", str(WORK_DIR),
        str(SPEC),
    ]
    print("+ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("error: PyInstaller failed", file=sys.stderr)
        return result.returncode

    bundle = DIST_DIR / NAME
    if not bundle.is_dir():
        print(f"error: expected bundle not found: {bundle}", file=sys.stderr)
        return 1
    exe_name = NAME + (".exe" if platform.system() == "Windows" else "")
    print(f"bundle:  {bundle}")
    print(f"run me:  {bundle / exe_name}")

    if not args.no_archive:
        suffix = "zip" if platform.system() == "Windows" else "tar.gz"
        archive = DIST_DIR / f"{NAME}-{project_version()}-{platform_tag()}.{suffix}"
        make_archive(bundle, archive)
        print(f"archive: {archive}")

    # app/build/ holds PyInstaller intermediates, including a bare bootloader exe
    # with no _internal/ payload. That exe looks runnable but always fails with
    # "Failed to load Python DLL", so drop the whole work dir unless asked.
    if not args.keep_build and WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
        print("note:    removed app/build/ (intermediates); pass --keep-build to keep it")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
