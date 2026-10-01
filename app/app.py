"""Qt entry point: ``python app/app.py`` (or ``python -m app``)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from app.log_bridge import LogEmitter, install_qt_logging
from app.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("umadump")
    app.setApplicationDisplayName("umadump")

    emitter = LogEmitter()
    install_qt_logging(emitter, verbose=False)

    window = MainWindow(emitter)
    window.show()

    # Headless verification hook: build the window, touch the event loop once,
    # optionally drop a marker file, and exit. Used to smoke-test frozen bundles.
    if "--smoke-test" in sys.argv:
        app.processEvents()
        detail = _smoke_test_detail()
        marker = os.environ.get("UMADUMP_SMOKE_MARKER")
        if marker:
            Path(marker).write_text(detail, encoding="utf-8")
        return 0 if detail.startswith("ok") else 1

    return app.exec()


def _smoke_test_detail() -> str:
    """Prove the bundled pipeline (incl. the lazily-imported minidump backend) loads."""
    checks = ["window"]
    try:
        from app.window import _default_output_dir

        checks.append(f"default_out={_default_output_dir()}")
        import main as umadump_main

        checks.append(f"main:extractors={len(umadump_main.EXTRACTORS)}")
        import minidump  # noqa: F401  - only imported lazily by MinidumpMemory at runtime

        checks.append("minidump")
    except Exception as exc:  # noqa: BLE001
        return f"fail {type(exc).__name__}: {exc}"
    return "ok " + " ".join(checks)


if __name__ == "__main__":
    raise SystemExit(main())
