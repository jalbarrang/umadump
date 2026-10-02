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
Rough size: ~112 MB unpacked (Windows) / ~153 MB (Linux), dominated by Qt.

There is no macOS build. Mac users run the **Windows** bundle inside the Wine bottle
that already hosts the game — see below.

### Linux via Docker

`app/build.py --docker` builds `app/Dockerfile.linux` and runs this same script inside
it, so a Windows or macOS host can produce the Linux bundle.

The base image is pinned by the Python 3.14 requirement rather than by Qt. PyInstaller
needs a shared `libpython`, and Ubuntu 22.04 (glibc 2.35) plus deadsnakes `python3.14`
is the lowest base that provides one, giving a **glibc 2.35 floor**: Ubuntu 22.04+,
Debian 12+, RHEL 9+.

The `PySide6<6.10` pin relaxed the Qt side: 6.8.3 ships its x86_64 wheel as
`manylinux_2_28` (6.11 shipped `manylinux_2_34`), so Qt no longer sets the floor.
Lowering it further means finding a 3.14 with a shared libpython on an older distro,
which is untested — leave the image alone until someone verifies that. (The aarch64
PySide6 wheel is `manylinux_2_39`, so arm64 needs glibc 2.39.)

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

**Qt must be < 6.10 or the app will not start.** Qt 6.10+ links `Qt6Core.dll` against
the OS-provided ICU DLLs (`icuuc.dll`, `icu.dll`). Windows ships those; Wine and
CrossOver do not, so a 6.10+ build dies at import with:

```
err:module:import_dll Library icuuc.dll (which is needed by Qt6Core.dll) not found
```

`app/requirements.txt` pins `PySide6>=6.8,<6.10` for exactly this reason. Verified on
macOS 26.6.2 / arm64 under Highball (CrossOver 26.3 engine): PySide6 6.11.2 fails to
import QtCore, while PySide6 6.8.3 renders a real window (`platformName: windows`, text
and colours rasterised correctly). Rebuild the Windows bundle with the pin before
handing it to Mac users.

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
| macOS | via the Windows build in the bottle | via the Windows build | no (use the Windows bundle) |

## Layout

| File | Purpose |
|------|---------|
| `app.py` | Entry point: `QApplication`, logging wiring, window; `--smoke-test` hook |
| `window.py` | Main window: source config, run controls, log console |
| `runner.py` | `ExtractionWorker` (`QThread`) driving the existing pipeline |
| `log_bridge.py` | `logging.Handler` → Qt signal bridge for live logs |
| `umadump-gui.spec` | PyInstaller spec (onedir, Qt add-ons excluded) |
| `build.py` | Local build + archive script (Windows, Linux) |
| `Dockerfile.linux` | Ubuntu 22.04 + deadsnakes builder for `--docker` (glibc 2.35 floor) |
| `requirements.txt` | Runtime deps (PySide6, minidump) |
| `requirements-build.txt` | Runtime deps + PyInstaller |
