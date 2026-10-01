#!/usr/bin/env python3
"""Build a portable umadump-gui bundle for the current OS with PyInstaller.

PyInstaller cannot cross-compile, so each target OS needs its own build:

  * Windows  — run this script on Windows (native).
  * Linux    — run this script on Linux, or from any host via ``--docker``.
  * macOS    — run this script on a Mac (produces ``umadump-gui.app``).

Outputs land under ``app/dist/<platform-tag>/`` so builds for different OSes
coexist (they are not wiped by each other):

  * ``app/dist/<tag>/umadump-gui/``          — runnable onedir bundle
  * ``app/dist/<tag>/umadump-gui.app``       — macOS app bundle
  * ``app/dist/<tag>/umadump-gui-<ver>-<tag>.zip|.tar.gz`` — archive

Usage::

    python app/build.py                 # build + archive on the current OS
    python app/build.py --no-archive    # build only
    python app/build.py --docker        # build the Linux bundle in a container
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
DOCKERFILE = APP_DIR / "Dockerfile.linux"
DOCKER_IMAGE = "umadump-linux-builder"
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
    """Archive *bundle* preserving the executable bit (and, on macOS, symlinks)."""
    if platform.system() == "Darwin" and shutil.which("ditto"):
        # ditto is the only tool that round-trips .app bundles correctly
        # (symlinks inside Frameworks/, extended attributes, exec bits).
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(out)], check=True)
    elif platform.system() == "Windows":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(bundle.parent))
    else:
        with tarfile.open(out, "w:gz") as tf:
            tf.add(bundle, arcname=bundle.name)


def find_bundle(platform_dir: Path) -> Path | None:
    """Return the runnable bundle produced in *platform_dir*, if any."""
    mac_app = platform_dir / f"{NAME}.app"
    if mac_app.is_dir():
        return mac_app
    onedir = platform_dir / NAME
    if onedir.is_dir():
        return onedir
    return None


def run_docker(passthrough: list[str]) -> int:
    """Build the Linux bundle inside Docker (usable from Windows/macOS hosts)."""
    if shutil.which("docker") is None:
        print("error: docker was not found on PATH.", file=sys.stderr)
        return 2
    if not DOCKERFILE.is_file():
        print(f"error: dockerfile not found: {DOCKERFILE}", file=sys.stderr)
        return 2

    build_cmd = ["docker", "build", "-f", str(DOCKERFILE), "-t", DOCKER_IMAGE, str(ROOT)]
    print("+ " + " ".join(build_cmd), flush=True)
    if subprocess.run(build_cmd, check=False).returncode != 0:
        print("error: docker image build failed", file=sys.stderr)
        return 1

    # Run the very same build script inside the container; it writes into the
    # bind-mounted repo, so artifacts appear under app/dist/linux-<arch>/.
    run_cmd = [
        "docker", "run", "--rm",
        "-v", f"{ROOT.as_posix()}:/src",
        "-w", "/src",
        DOCKER_IMAGE,
        "python", "app/build.py", "--in-container", *passthrough,
    ]
    print("+ " + " ".join(run_cmd), flush=True)
    return subprocess.run(run_cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the umadump-gui bundle for this platform.")
    parser.add_argument("--no-archive", action="store_true", help="Skip creating the archive.")
    parser.add_argument("--keep-build", action="store_true",
                        help="Keep app/build/ (intermediate files; useful only for debugging).")
    parser.add_argument("--docker", action="store_true",
                        help="Build the Linux bundle in a container (works from any host OS).")
    parser.add_argument("--in-container", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.docker:
        if args.in_container:
            print("error: --docker cannot be combined with --in-container", file=sys.stderr)
            return 2
        passthrough = [flag for flag, on in
                       (("--no-archive", args.no_archive), ("--keep-build", args.keep_build)) if on]
        return run_docker(passthrough)

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

    tag = platform_tag()
    platform_dir = DIST_DIR / tag
    work_dir = WORK_DIR / tag
    for stale in (platform_dir, work_dir):
        if stale.exists():
            shutil.rmtree(stale)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(platform_dir),
        "--workpath", str(work_dir),
        str(SPEC),
    ]
    print("+ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        print("error: PyInstaller failed", file=sys.stderr)
        return result.returncode

    bundle = find_bundle(platform_dir)
    if bundle is None:
        print(f"error: expected bundle not found under {platform_dir}", file=sys.stderr)
        return 1
    entry = bundle / "Contents" / "MacOS" / NAME if bundle.suffix == ".app" else bundle / (
        NAME + (".exe" if platform.system() == "Windows" else "")
    )
    print(f"bundle:  {bundle}")
    print(f"run me:  {entry}")

    if not args.no_archive:
        suffix = "tar.gz" if platform.system() == "Linux" else "zip"
        archive = platform_dir / f"{NAME}-{project_version()}-{tag}.{suffix}"
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
