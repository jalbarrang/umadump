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

## Packaging (Windows + Linux)

Portable PyInstaller bundles are built **locally on each OS** — PyInstaller cannot
cross-compile, so a Windows build must run on Windows and a Linux build on Linux.

```powershell
pip install -r app/requirements-build.txt
python app/build.py                  # bundle + archive
python app/build.py --no-archive     # bundle only
```

Outputs (git-ignored):

| Path | Contents |
|------|----------|
| `app/dist/umadump-gui/` | runnable onedir bundle (`umadump-gui.exe` / `umadump-gui`) |
| `app/dist/umadump-gui-<ver>-<os>-<arch>.zip` | Windows archive (`.tar.gz` on Linux) |

Rough size: ~112 MB unpacked, ~47 MB compressed (dominated by Qt).

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
QT_QPA_PLATFORM=offscreen UMADUMP_SMOKE_MARKER=smoke.txt ./app/dist/umadump-gui/umadump-gui.exe --smoke-test
cat smoke.txt   # -> "ok window main:extractors=12 minidump"
```

### Platform support

| OS | Live process | Minidump | Bundle |
|----|--------------|----------|--------|
| Windows | yes | yes | yes |
| Linux | yes (game under Wine/Proton) | yes | yes |
| macOS | no | not packaged | no |

macOS is intentionally excluded: `memory.py` has no macOS backend (it guards on
`os.name == "nt"` and otherwise assumes Linux `/proc` + `process_vm_readv`), and its
`_LibCAPI` constructor loads `libc.so.6` at import time, which does not exist on macOS.
`app/build.py` refuses to build there with an explanatory error.

## Layout

| File | Purpose |
|------|---------|
| `app.py` | Entry point: `QApplication`, logging wiring, window; `--smoke-test` hook |
| `window.py` | Main window: source config, run controls, log console |
| `runner.py` | `ExtractionWorker` (`QThread`) driving the existing pipeline |
| `log_bridge.py` | `logging.Handler` → Qt signal bridge for live logs |
| `umadump-gui.spec` | PyInstaller spec (onedir, Qt add-ons excluded) |
| `build.py` | Cross-platform local build + archive script |
| `requirements.txt` | Runtime deps (PySide6, minidump) |
| `requirements-build.txt` | Runtime deps + PyInstaller |
