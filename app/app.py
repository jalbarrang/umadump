"""Dear PyGui entry point: ``python app/app.py`` (or ``python -m app``)."""
from __future__ import annotations

import os
import queue
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dearpygui.dearpygui as dpg

from app.log_bridge import GuiEvent, install_queue_logging
from app.window import VIEWPORT_TITLE, MainWindow


def main() -> int:
    events: queue.Queue[GuiEvent] = queue.Queue()
    install_queue_logging(events, verbose=False)

    dpg.create_context()
    window = MainWindow(events)
    window.build()

    # Headless verification hook: build the whole item tree (which needs no
    # viewport), optionally drop a marker file, and exit. Used to smoke-test
    # frozen bundles, including on machines with no display.
    if "--smoke-test" in sys.argv:
        detail = _smoke_test_detail(window)
        marker = os.environ.get("UMADUMP_SMOKE_MARKER")
        if marker:
            Path(marker).write_text(detail, encoding="utf-8")
        dpg.destroy_context()
        return 0 if detail.startswith("ok") else 1

    dpg.create_viewport(title=VIEWPORT_TITLE, width=1020, height=780, min_width=780, min_height=520)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window(MainWindow.ROOT, True)
    try:
        while dpg.is_dearpygui_running():
            window.drain()
            dpg.render_dearpygui_frame()
    finally:
        window.shutdown()
        dpg.destroy_context()
    return 0


def _smoke_test_detail(window: MainWindow) -> str:
    """Prove the bundled pipeline (incl. the lazily-imported minidump backend) loads."""
    checks = ["window"]
    try:
        from app.window import _default_output_dir

        checks.append(f"default_out={_default_output_dir()}")
        import main as umadump_main

        checks.append(f"main:extractors={len(umadump_main.EXTRACTORS)}")
        import minidump  # noqa: F401  - only imported lazily by MinidumpMemory at runtime

        checks.append("minidump")
        import dearpygui  # noqa: F401  - the GUI toolkit

        checks.append("dearpygui")
        checks.append(f"ui={Path(window.ui_font_path or 'default').name}")
        checks.append(f"mono={Path(window.mono_font_path or 'default').name}")
        if not window.built:
            raise RuntimeError("GUI item tree was not built")
    except Exception as exc:  # noqa: BLE001
        return f"fail {type(exc).__name__}: {exc}"
    return "ok " + " ".join(checks)


if __name__ == "__main__":
    raise SystemExit(main())
