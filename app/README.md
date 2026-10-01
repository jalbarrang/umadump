# umadump GUI (quick cockpit)

A thin PySide6 front-end over the existing CLI pipeline. It reuses `main.py`'s
orchestration helpers directly, so the GUI and the CLI stay on the same code path.

## What it does today

- Choose a source: **live process** or a **minidump** (+ `global-metadata.dat`).
- Run **schema validation only**, a **single extractor pass**, or a **daemon loop**
  (live only) with a configurable poll interval.
- Pick the **output folder** the JSON files are written to.
- Watch the full `umadump` log stream live in the console (level-coloured), with the
  same messages the CLI prints.

This is intentionally the "launcher + log console" slice: enough to drive every
existing feature and see where the UI wants to go next.

## Setup (local venv)

```powershell
python -m venv app/.venv
app/.venv/Scripts/python -m pip install -r app/requirements.txt
```

## Run

```powershell
app/.venv/Scripts/python app/app.py
# or
app/.venv/Scripts/python -m app
```

## Packaging (Windows, Linux, macOS)

PyInstaller cannot cross-compile, so every OS needs its own build (and its own host).
Outputs are written per platform, so builds for different OSes coexist.

Install the build deps for the current OS from `app/requirements-build.txt`. With uv that
is a single command with no venv bookkeeping:

```bash
uv run --no-project --python 3.14 --with-requirements app/requirements-build.txt python app/build.py
```

Or with pip inside an activated venv (`pip install -r app/requirements-build.txt`), then:

| Target | Build host | Command | Artifact |
|--------|-----------|---------|----------|
| Windows | Windows | `python app/build.py` | `app/dist/windows-x86_64/umadump-gui/` + `.zip` |
| Linux | any host with Docker | `python app/build.py --docker` | `app/dist/linux-x86_64/umadump-gui/` + `.tar.gz` |
| macOS | a Mac | `python app/build.py` | `app/dist/macos-<arch>/umadump-gui.app` + `.zip` |

 `--no-archive` skips the archive; `--keep-build` keeps PyInstaller's intermediates.
Rough size: ~112 MB unpacked (Windows) / ~153 MB (Linux), dominated by Qt.

### Linux via Docker

`app/build.py --docker` builds `app/Dockerfile.linux` and runs this same script inside
it, so a Windows or macOS host can produce the Linux bundle.

The base image is chosen deliberately. PySide6 6.11 ships its x86_64 wheel as
`manylinux_2_34`, i.e. **Qt itself requires glibc >= 2.34**, so nothing older is
reachable. `python:3.14-slim-bookworm` (glibc 2.36) would raise the floor to 2.36 and
lock out Ubuntu 22.04 LTS, and `manylinux_2_34`'s cp314 has no shared libpython, which
PyInstaller requires. Ubuntu 22.04 (glibc 2.35) plus deadsnakes `python3.14` is the
lowest base satisfying both, giving a **glibc 2.35 floor**: Ubuntu 22.04+, Debian 12+,
RHEL 9+. (The aarch64 PySide6 wheel is `manylinux_2_39`, so arm64 needs glibc 2.39.)

### macOS

Build it on the Mac with uv:

```bash
uv run --no-project --python 3.14 --with-requirements app/requirements-build.txt python app/build.py
```

uv's managed CPython ships a shared `libpython`, which PyInstaller requires (verified
`Py_ENABLE_SHARED = 1`), so nothing extra is needed. Equivalently, an explicit venv:
`uv venv --python 3.14 app/.venv`, `uv pip install --python app/.venv/bin/python -r
app/requirements-build.txt`, then `app/.venv/bin/python app/build.py`.

The spec adds a `BUNDLE` step on Darwin, so macOS produces a real `umadump-gui.app`
(bundle id `com.umadump.gui`). It is unsigned, so Gatekeeper will object on first open —
right-click → Open, or `xattr -dr com.apple.quarantine umadump-gui.app`. Build on Apple
silicon and on Intel separately if you need both architectures (the macOS dependency set
resolves for both on Python 3.14, including `macholib`).

**Live memory reading is not available on macOS yet.** `memory.py` has no macOS backend
(it guards on `os.name == "nt"` and otherwise assumes Linux `/proc` +
`process_vm_readv`), so a Mac build is minidump-only, and the GUI disables the
"Live process" option there. Reading the game's Wine process on macOS is planned via a
Frida-backed `MemoryReader` (same approach as `honse-sim`'s career exporter, which
already drives a Windows `frida-server` inside the Wine prefix).

> **Run the bundle from `app/dist/`, not `app/build/`.** PyInstaller writes a bare
> bootloader `umadump-gui.exe` into `app/build/umadump-gui/` during the build. It has
> no `_internal/` payload, so launching it fails with
> `Failed to load Python DLL ... python314.dll`. `build.py` now deletes that work
> directory on success (use `--keep-build` only when debugging the build itself).

The archive unpacks to a single `umadump-gui/` folder; keep `umadump-gui.exe` next to
its `_internal/` folder and run the exe.

### Output location

| Context | Default output folder |
|---------|-----------------------|
| From source (`python app/app.py`) | the repository root |
| Frozen bundle | `umadump-dumps/` next to the executable |

Never derive it from `__file__` in a frozen build: that resolves under `_internal/` and
would write JSON into the app's own install directory. The chosen folder (plus mode,
paths, poll interval and checkbox states) is remembered between launches via
`QSettings("umadump", "umadump-gui")` — the registry on Windows,
`~/.config/umadump/umadump-gui.conf` on Linux.

Verify a built bundle without a display:

```powershell
# Windows
QT_QPA_PLATFORM=offscreen UMADUMP_SMOKE_MARKER=smoke.txt ./app/dist/windows-x86_64/umadump-gui/umadump-gui.exe --smoke-test
cat smoke.txt   # ok window default_out=<bundle>/umadump-dumps main:extractors=12 minidump

# Linux (host has no Python -- the bundle is self-contained)
docker run --rm -v "$PWD:/src" -w /src ubuntu:22.04 bash -lc \
  'QT_QPA_PLATFORM=offscreen ./app/dist/linux-x86_64/umadump-gui/umadump-gui --smoke-test'
```

### Platform support

| OS | Live process | Minidump | Bundle |
|----|--------------|----------|--------|
| Windows | yes | yes | yes |
| Linux | yes (game under Wine/Proton) | yes | yes |
| macOS | no (Frida backend planned) | yes | yes |

## Layout

| File | Purpose |
|------|---------|
| `app.py` | Entry point: `QApplication`, logging wiring, window; `--smoke-test` hook |
| `window.py` | Main window: source config, run controls, log console |
| `runner.py` | `ExtractionWorker` (`QThread`) driving the existing pipeline |
| `log_bridge.py` | `logging.Handler` → Qt signal bridge for live logs |
| `umadump-gui.spec` | PyInstaller spec (onedir, Qt add-ons excluded) |
| `build.py` | Cross-platform local build + archive script |
| `Dockerfile.linux` | Ubuntu 22.04 + deadsnakes builder for `--docker` (glibc 2.35 floor) |
| `requirements.txt` | Runtime deps (PySide6, minidump) |
| `requirements-build.txt` | Runtime deps + PyInstaller |
