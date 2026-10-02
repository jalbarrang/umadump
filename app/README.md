# umadump GUI (quick cockpit)

A thin [Dear PyGui](https://github.com/hoffstadt/DearPyGui) front-end over the existing
CLI pipeline. It reuses `main.py`'s orchestration helpers directly, so the GUI and the
CLI stay on the same code path.

Dear PyGui is MIT-licensed and draws its own widgets, so the bundle carries no Qt.

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

## Packaging (Windows, Linux)

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

 `--no-archive` skips the archive; `--keep-build` keeps PyInstaller's intermediates.
Rough size: **~27 MB unpacked**, dominated by the Python runtime and Dear PyGui's SDL2
back end. The previous Qt build was ~106 MB.

There is no macOS build. Mac users run the **Windows** bundle inside the Wine bottle
that already hosts the game — see below.

### Linux via Docker

`app/build.py --docker` builds `app/Dockerfile.linux` and runs this same script inside
it, so a Windows or macOS host can produce the Linux bundle.

The base image is pinned by the Python 3.14 requirement, not by any GUI dependency.
PyInstaller needs a shared `libpython`, and Ubuntu 22.04 (glibc 2.35) plus deadsnakes
`python3.14` is the lowest base that provides one, giving a **glibc 2.35 floor**:
Ubuntu 22.04+, Debian 12+, RHEL 9+. Nothing in the current dependency set raises it.

### macOS: run the Windows build in the bottle

Mac users do not get a native build. The game already runs inside a Wine bottle
(Highball, CrossOver, Whisky), so the **Windows** bundle runs there too and reads the
game with the same `WindowsProcessMemory` backend it uses on Windows — no extra
backend, no helper process, no special privileges.

Host-side reading is not an option on Apple silicon, which is why this is the route:

- `task_for_pid` is refused for the Rosetta-translated Wine process, so a Mach backend
  — and Frida's own macOS attach, which needs the same task port — cannot reach it.
  Unlocking that means disabling SIP or enabling developer mode.
- Frida's macOS agent is **arm64-only**, so it cannot load into the x86_64 guest even
  if the task port were granted.

Unpack the Windows bundle into the bottle and run it with the engine that owns the
bottle (Highball shown; CrossOver and Whisky have the same shape):

```bash
WINEPREFIX="$HOME/Library/Application Support/Highball/bottles/Games" \
  "<engine>/bin/wine" 'C:\path\to\umadump-gui\umadump-gui.exe'
```

Or add it as a shortcut in the bottle's UI (a Highball pin, CrossOver's Run Command).
Output JSON lands on Windows paths inside the bottle — `.../drive_c/umadump-dumps/`,
i.e. `~/Library/Application Support/Highball/bottles/Games/drive_c/umadump-dumps/`
from the Mac side.

**No Qt, so none of the old Wine workarounds apply.** The Qt build had to be pinned to
`PySide6<6.10` because Qt 6.10+ links `Qt6Core.dll` against OS-provided ICU DLLs that
Wine and CrossOver do not ship, and it died at import with
`err:module:import_dll Library icuuc.dll ... not found`. Dear PyGui has no such
dependency. Verified on macOS 26.6.2 / arm64 under Highball (CrossOver 26.3 engine): the
window renders normally.

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
| Frozen bundle | `umadump-dumps/` **beside** the bundle folder, never inside it |

Never derive it from `__file__` in a frozen build: that resolves under `_internal/`. The
same trap applies to `sys.executable.parent`, which for a onedir build *is* the bundle
folder — so an earlier version wrote user dumps into `umadump-gui/umadump-dumps/`, inside
the very folder that gets archived, and a rebuild afterwards would have shipped that game
data. Frozen builds now step out of the bundle, and `build.py` additionally refuses to
put a `umadump-dumps/` folder into any archive as a second line of defence.

The chosen folder (plus mode, paths, poll interval and checkbox states) is remembered
between launches in `umadump-gui.json` under the per-user config dir —
`%APPDATA%\umadump\` on Windows, `~/.config/umadump/` on Linux,
`~/Library/Application Support/umadump/` on macOS.

### Fonts

The GUI bundles its own fonts in `app/fonts/` rather than depending on the host:

| Role | Font | Size | License |
|------|------|------|---------|
| UI | Roboto | 16 px | Apache-2.0 |
| Log console | JetBrains Mono | 14 px | OFL-1.1 |

Dear PyGui's built-in face is an ASCII-only bitmap font that renders `...` as `?`.
System fonts (Segoe UI/Consolas, DejaVu, Liberation) are still tried after the bundled
ones as a fallback, and user-facing strings are ASCII throughout so the GUI stays
correct even if every font is missing. See `app/fonts/README.md` for provenance.

Verify a built bundle without a display:

```powershell
# Windows
UMADUMP_SMOKE_MARKER=smoke.txt ./app/dist/windows-x86_64/umadump-gui/umadump-gui.exe --smoke-test
cat smoke.txt   # ok window default_out=<bundle>/umadump-dumps main:extractors=12 minidump dearpygui

# Linux (host has no Python -- the bundle is self-contained apart from libxcb1)
docker run --rm -v "$PWD:/src" -w /src ubuntu:22.04 bash -lc \
  'apt-get update -qq && apt-get install -y -qq libxcb1 && \
   ./app/dist/linux-x86_64/umadump-gui/umadump-gui --smoke-test'
```

The smoke test builds the whole item tree but never creates a viewport, so it needs no
display and works on a headless machine (no Xvfb, no `QT_QPA_PLATFORM`).

**Linux expects `libxcb1` from the system.** PyInstaller deliberately never bundles
`libxcb` — its ABI shifts between distro releases, so it is treated as a system library
(see `PyInstaller/depend/dylib.py`). Every desktop install already has it; a bare
container does not, which is why the command above installs it. Without it the bundle
dies at import with `ImportError: libxcb.so.1: cannot open shared object file`.

The `linux-<arch>` tag follows the build host, so a container on Apple silicon produces
`linux-arm64`.

### Platform support

| OS | Live process | Minidump | Bundle |
|----|--------------|----------|--------|
| Windows | yes | yes | yes |
| Linux | yes (game under Wine/Proton) | yes | yes |
| macOS | via the Windows build in the bottle | via the Windows build | no (use the Windows bundle) |

## Layout

| File | Purpose |
|------|---------|
| `app.py` | Entry point: Dear PyGui context/viewport, logging wiring, render loop; `--smoke-test` hook |
| `window.py` | Main window: source config, run controls, log console, settings |
| `runner.py` | `ExtractionWorker` (`threading.Thread`) driving the existing pipeline |
| `log_bridge.py` | `logging.Handler` → thread-safe event queue the render loop drains |
| `umadump-gui.spec` | PyInstaller spec (onedir) |
| `build.py` | Local build + archive script (Windows, Linux) |
| `Dockerfile.linux` | Ubuntu 22.04 + deadsnakes builder for `--docker` (glibc 2.35 floor) |
| `requirements.txt` | Runtime deps (dearpygui, minidump) |
| `requirements-build.txt` | Runtime deps + PyInstaller |
