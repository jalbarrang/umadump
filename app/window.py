"""Main window: source configuration, run controls, and a live log console."""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any, Final

import dearpygui.dearpygui as dpg

from app.log_bridge import FailedEvent, FinishedEvent, GuiEvent, LogEvent, StateEvent
from app.runner import ExtractionWorker
from logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIEWPORT_TITLE: Final = "umadump - extractor console"

LIVE_LABEL: Final = "Live process"
MINIDUMP_LABEL: Final = "Minidump"

# Keep the console bounded; Dear PyGui text items are real widgets, so an
# unbounded log would grow the item tree without limit.
MAX_LOG_LINES: Final = 2000
# Never spend a whole frame draining a backlog: the render loop has to breathe.
MAX_EVENTS_PER_FRAME: Final = 400

_LEVEL_COLORS: dict[int, tuple[int, int, int, int]] = {
    logging.DEBUG: (138, 138, 138, 255),
    logging.INFO: (216, 216, 216, 255),
    logging.WARNING: (224, 160, 48, 255),
    logging.ERROR: (224, 92, 92, 255),
    logging.CRITICAL: (255, 77, 77, 255),
}
_DEFAULT_LOG_COLOR: Final = (216, 216, 216, 255)

_OPEN_WITH: Final[dict[str, str]] = {"win32": "explorer", "darwin": "open"}

# Dear PyGui ships a small ASCII-only bitmap font (ProggyClean), which renders "..."
# and "-" as '?' and looks dated. Bind a real system font instead. DPG 2.x builds
# the atlas from the whole file, so no explicit glyph ranges are needed. Candidate
# lists are per-platform, and a Wine bottle has neither Segoe UI nor Consolas, so
# the fallbacks matter.
_UI_FONT_CANDIDATES: Final[tuple[str, ...]] = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\LiberationSans-Regular.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)
_MONO_FONT_CANDIDATES: Final[tuple[str, ...]] = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
)
_UI_FONT_SIZE: Final = 16
_MONO_FONT_SIZE: Final = 15

# Vertical room the log must leave for the separator and status line under it.
# A child window sized ``-1`` swallows the rest of the window and the status text
# is then clipped away entirely.
_STATUS_RESERVE: Final = 44


def _first_existing_font(candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate font file that exists, else ``None``."""
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def _default_output_dir() -> Path:
    """Default dump location.

    In a PyInstaller bundle ``__file__`` lives under ``_internal/``, so deriving a
    default from it would write JSON *inside* the app's own install directory.
    Frozen builds therefore default to a sibling folder next to the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "umadump-dumps"
    return PROJECT_ROOT


def _settings_path() -> Path:
    """Per-user settings file, alongside the other umadump config."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "umadump" / "umadump-gui.json"


def _picked_path(app_data: object) -> str:
    """Pull the chosen path out of a file-dialog payload."""
    if isinstance(app_data, dict):
        picked = app_data.get("file_path_name") or app_data.get("current_path")
        return str(picked or "")
    return str(app_data or "")


class MainWindow:
    """Builds the Dear PyGui item tree and owns the worker lifecycle."""

    ROOT: Final = "root_window"
    SOURCE_TABLE: Final = "source_table"
    MODE: Final = "mode_radio"
    MINIDUMP: Final = "minidump_input"
    BTN_MINIDUMP: Final = "minidump_browse"
    METADATA: Final = "metadata_input"
    BTN_METADATA: Final = "metadata_browse"
    OUTPUT: Final = "output_input"
    BTN_OUTPUT: Final = "output_browse"
    BTN_VALIDATE: Final = "btn_validate"
    BTN_ONCE: Final = "btn_once"
    BTN_DAEMON: Final = "btn_daemon"
    POLL: Final = "poll_input"
    VERBOSE: Final = "verbose_check"
    UPDATE_CHECK: Final = "update_check"
    BTN_OPEN_OUTPUT: Final = "btn_open_output"
    LOG: Final = "log_child"
    STATUS: Final = "status_text"
    DLG_MINIDUMP: Final = "dlg_minidump"
    DLG_METADATA: Final = "dlg_metadata"
    DLG_OUTPUT: Final = "dlg_output"

    def __init__(self, events: queue.Queue[GuiEvent]) -> None:
        self._events = events
        self._worker: ExtractionWorker | None = None
        self._default_output_dir = _default_output_dir()
        self._mono_font: int | str | None = None
        self._log_items: deque[int | str] = deque()
        self._wrap_width: int = -1
        self.built = False

    # ------------------------------------------------------------------ UI
    def build(self) -> None:
        """Create every item. Safe without a viewport, which keeps the smoke test headless."""
        with dpg.window(tag=self.ROOT):
            self._build_source()
            self._build_run()
            self._build_log()
            dpg.add_separator()
            dpg.add_text("Idle", tag=self.STATUS, color=_DEFAULT_LOG_COLOR)

        self._build_file_dialogs()
        self._load_fonts()
        self._load_settings()
        self.built = True

    def _build_source(self) -> None:
        dpg.add_text("Source")
        dpg.add_separator()
        with dpg.table(header_row=False, width=-1, policy=dpg.mvTable_SizingStretchProp,
                       tag=self.SOURCE_TABLE):
            dpg.add_table_column(init_width_or_weight=160, width_fixed=True)
            dpg.add_table_column(init_width_or_weight=1.0)

            with dpg.table_row():
                dpg.add_text("Mode")
                dpg.add_radio_button((LIVE_LABEL, MINIDUMP_LABEL), default_value=LIVE_LABEL,
                                     horizontal=True, tag=self.MODE, callback=self._on_mode_changed)

            with dpg.table_row():
                dpg.add_text("Minidump")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag=self.MINIDUMP, width=-110,
                                       hint="Path to a full-memory .dmp file")
                    dpg.add_button(label="Browse...", tag=self.BTN_MINIDUMP,
                                   callback=lambda: dpg.show_item(self.DLG_MINIDUMP))

            with dpg.table_row():
                dpg.add_text("global-metadata.dat")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag=self.METADATA, width=-110,
                                       hint="Auto-derived from the game exe in live mode")
                    dpg.add_button(label="Browse...", tag=self.BTN_METADATA,
                                   callback=lambda: dpg.show_item(self.DLG_METADATA))

            with dpg.table_row():
                dpg.add_text("Output folder")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag=self.OUTPUT, width=-110)
                    dpg.add_button(label="Browse...", tag=self.BTN_OUTPUT,
                                   callback=lambda: dpg.show_item(self.DLG_OUTPUT))

    def _build_run(self) -> None:
        dpg.add_spacer(height=6)
        dpg.add_text("Run")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Validate schema", tag=self.BTN_VALIDATE,
                           callback=lambda: self._start("validate"))
            dpg.add_button(label="Run once", tag=self.BTN_ONCE,
                           callback=lambda: self._start("once"))
            dpg.add_button(label="Start daemon", tag=self.BTN_DAEMON,
                           callback=self._toggle_daemon)
            dpg.add_spacer(width=18)
            dpg.add_text("Poll (s)")
            dpg.add_input_double(tag=self.POLL, default_value=2.0, min_value=0.1, max_value=120.0,
                                 step=0.5, format="%.1f", width=90)
            dpg.add_spacer(width=12)
            dpg.add_checkbox(label="Verbose", tag=self.VERBOSE, default_value=False)
            dpg.add_checkbox(label="Update check", tag=self.UPDATE_CHECK, default_value=True)
            dpg.add_spacer(width=12)
            dpg.add_button(label="Open output folder", tag=self.BTN_OPEN_OUTPUT,
                           callback=self._open_output_dir)

    def _build_log(self) -> None:
        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            dpg.add_text("Log")
            dpg.add_spacer(width=12)
            dpg.add_button(label="Clear", callback=self._clear_log)
        dpg.add_separator()
        # height=-<reserve> rather than -1: the child fills the window but leaves the
        # status line below it somewhere to live.
        dpg.add_child_window(tag=self.LOG, height=-_STATUS_RESERVE, width=-1, border=True)

    def _build_file_dialogs(self) -> None:
        common = {"show": False, "width": 760, "height": 460, "modal": False,
                  "default_path": str(self._default_output_dir)}
        with dpg.file_dialog(tag=self.DLG_MINIDUMP, callback=self._on_minidump_picked, **common):
            dpg.add_file_extension(".dmp")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(tag=self.DLG_METADATA, callback=self._on_metadata_picked, **common):
            dpg.add_file_extension(".dat")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(tag=self.DLG_OUTPUT, callback=self._on_output_picked,
                             directory_selector=True, **common):
            pass

    def _load_fonts(self) -> None:
        """Bind real UI/mono fonts when the OS has them, else keep DPG's default."""
        ui_path = _first_existing_font(_UI_FONT_CANDIDATES)
        mono_path = _first_existing_font(_MONO_FONT_CANDIDATES)
        if ui_path is None and mono_path is None:
            return
        with dpg.font_registry():
            if ui_path is not None:
                with dpg.font(ui_path, _UI_FONT_SIZE) as ui_font:
                    pass
                dpg.bind_font(ui_font)
            if mono_path is not None:
                with dpg.font(mono_path, _MONO_FONT_SIZE) as mono_font:
                    pass
                self._mono_font = mono_font

    # -------------------------------------------------------------- actions
    def _clear_log(self) -> None:
        dpg.delete_item(self.LOG, children_only=True)
        self._log_items.clear()

    def _on_minidump_picked(self, _sender: object, app_data: object, _user: object) -> None:
        if path := _picked_path(app_data):
            dpg.set_value(self.MINIDUMP, path)

    def _on_metadata_picked(self, _sender: object, app_data: object, _user: object) -> None:
        if path := _picked_path(app_data):
            dpg.set_value(self.METADATA, path)

    def _on_output_picked(self, _sender: object, app_data: object, _user: object) -> None:
        if path := _picked_path(app_data):
            dpg.set_value(self.OUTPUT, path)

    def _open_output_dir(self) -> None:
        path = Path(str(dpg.get_value(self.OUTPUT)) or self._default_output_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
            subprocess.Popen([_OPEN_WITH.get(sys.platform, "xdg-open"), str(path)])
        except OSError as exc:
            logger.warning("Could not open %s: %s", path, exc)

    def _on_mode_changed(self) -> None:
        self._apply_mode_state()

    def _apply_mode_state(self) -> None:
        live = dpg.get_value(self.MODE) == LIVE_LABEL
        for tag in (self.MINIDUMP, self.BTN_MINIDUMP):
            dpg.configure_item(tag, enabled=not live)
        # Daemon mode only makes sense against a live process.
        dpg.configure_item(self.BTN_DAEMON, enabled=live)
        if not live and self._worker is not None and self._worker.mode == "daemon":
            self._worker.request_stop()

    def _toggle_daemon(self) -> None:
        if self._worker is not None and self._worker.mode == "daemon":
            self._worker.request_stop()
            dpg.set_item_label(self.BTN_DAEMON, "Stopping...")
            dpg.configure_item(self.BTN_DAEMON, enabled=False)
        else:
            self._start("daemon")

    def _start(self, mode: str) -> None:
        if self._worker is not None:
            return

        minidump = str(dpg.get_value(self.MINIDUMP)).strip()
        metadata = str(dpg.get_value(self.METADATA)).strip()
        if dpg.get_value(self.MODE) != LIVE_LABEL:
            if not minidump:
                self._append_log("ERROR: Minidump mode needs a .dmp path.", logging.ERROR)
                return
            if not metadata:
                self._append_log("ERROR: Minidump mode needs a global-metadata.dat path.",
                                 logging.ERROR)
                return

        verbose = bool(dpg.get_value(self.VERBOSE))
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        self._set_running(True, mode)
        worker = ExtractionWorker(
            self._events,
            mode=mode,
            minidump=minidump,
            metadata_path=metadata or None,
            output_dir=str(dpg.get_value(self.OUTPUT)).strip() or str(self._default_output_dir),
            poll_interval=float(dpg.get_value(self.POLL)),
            verbose=verbose,
            update_check=bool(dpg.get_value(self.UPDATE_CHECK)),
            validate_only=(mode == "validate"),
        )
        self._worker = worker
        worker.start()

    # -------------------------------------------------------------- events
    def drain(self) -> None:
        """Render queued worker/log events. Call once per frame, main thread only."""
        self._sync_wrap()
        for _ in range(MAX_EVENTS_PER_FRAME):
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, LogEvent):
                self._append_log(event.text, event.level)
            elif isinstance(event, StateEvent):
                dpg.set_value(self.STATUS, event.text)
            elif isinstance(event, FinishedEvent):
                self._append_log(event.summary, logging.INFO)
                dpg.set_value(self.STATUS, event.summary)
            elif isinstance(event, FailedEvent):
                self._append_log(event.message, logging.ERROR)
                dpg.set_value(self.STATUS, "Failed")

        self._reap_worker()

    def _reap_worker(self) -> None:
        worker = self._worker
        if worker is not None and not worker.is_alive():
            self._worker = None
            self._set_running(False, None)

    def _append_log(self, text: str, level: int) -> None:
        item = dpg.add_text(text, parent=self.LOG, wrap=self._wrap_width,
                            color=_LEVEL_COLORS.get(level, _DEFAULT_LOG_COLOR))
        if self._mono_font is not None:
            dpg.bind_item_font(item, self._mono_font)
        self._log_items.append(item)
        # A deque keeps the cap O(1); re-reading the child's children per line was O(n).
        while len(self._log_items) > MAX_LOG_LINES:
            dpg.delete_item(self._log_items.popleft())
        dpg.set_y_scroll(self.LOG, dpg.get_y_scroll_max(self.LOG))

    def _sync_wrap(self) -> None:
        """Wrap log lines to the console width so long output cannot clip.

        The width is only known once a viewport has laid the child window out, so
        this runs per frame and re-wraps existing lines only when it changes.
        """
        size = dpg.get_item_rect_size(self.LOG)
        if not size or size[0] <= 0:
            return
        width = max(160, int(size[0]) - 28)  # leave room for padding/scrollbar
        if abs(width - self._wrap_width) < 8:
            return
        self._wrap_width = width
        for item in self._log_items:
            dpg.configure_item(item, wrap=width)

    def _set_running(self, running: bool, mode: str | None) -> None:
        for tag in (self.MODE, self.MINIDUMP, self.BTN_MINIDUMP, self.METADATA, self.BTN_METADATA,
                    self.OUTPUT, self.BTN_OUTPUT, self.BTN_VALIDATE, self.BTN_ONCE, self.POLL,
                    self.VERBOSE, self.UPDATE_CHECK):
            dpg.configure_item(tag, enabled=not running)
        if running:
            dpg.configure_item(self.BTN_DAEMON, enabled=mode == "daemon")
            dpg.set_item_label(self.BTN_DAEMON, "Stop daemon" if mode == "daemon" else "Start daemon")
        else:
            dpg.set_item_label(self.BTN_DAEMON, "Start daemon")
            self._apply_mode_state()

    # -------------------------------------------------------------- settings
    def _load_settings(self) -> None:
        data: dict[str, Any] = {}
        try:
            loaded = json.loads(_settings_path().read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            pass  # first run, or a hand-edited file; defaults are fine

        dpg.set_value(self.MODE, MINIDUMP_LABEL if data.get("mode") == "minidump" else LIVE_LABEL)
        dpg.set_value(self.MINIDUMP, str(data.get("minidump") or ""))
        dpg.set_value(self.METADATA, str(data.get("metadata") or ""))
        dpg.set_value(self.OUTPUT, str(data.get("output_dir") or "") or str(self._default_output_dir))
        poll = data.get("poll_interval")
        dpg.set_value(self.POLL, float(poll) if isinstance(poll, (int, float)) else 2.0)
        dpg.set_value(self.VERBOSE, bool(data.get("verbose", False)))
        dpg.set_value(self.UPDATE_CHECK, bool(data.get("update_check", True)))
        self._apply_mode_state()

    def _save_settings(self) -> None:
        path = _settings_path()
        payload = {
            "mode": "minidump" if dpg.get_value(self.MODE) == MINIDUMP_LABEL else "live",
            "minidump": str(dpg.get_value(self.MINIDUMP)),
            "metadata": str(dpg.get_value(self.METADATA)),
            "output_dir": str(dpg.get_value(self.OUTPUT)),
            "poll_interval": float(dpg.get_value(self.POLL)),
            "verbose": bool(dpg.get_value(self.VERBOSE)),
            "update_check": bool(dpg.get_value(self.UPDATE_CHECK)),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save settings to %s: %s", path, exc)

    # -------------------------------------------------------------- cleanup
    def shutdown(self) -> None:
        """Persist settings and stop any running worker. Called on viewport close."""
        self._save_settings()
        worker = self._worker
        if worker is not None:
            worker.request_stop()
            worker.join(timeout=5.0)
            self._worker = None
