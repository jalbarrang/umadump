#!/usr/bin/env python3
"""Interactive Textual frontend for umadump."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Select, Static
from textual.worker import Worker, get_current_worker

from logger import logger
from update_check import CURRENT_VERSION, check_for_updates


class SessionProtocol(Protocol):
    def __enter__(self) -> SessionProtocol: ...

    def __exit__(self, *_: Any) -> None: ...

    def is_alive(self) -> bool: ...

    def run_pass(self) -> Any: ...


SessionFactory = Callable[[Optional[str], Optional[str], Optional[Callable[[], bool]]], SessionProtocol]


@dataclass(frozen=True)
class TuiOptions:
    minidump: Optional[str]
    metadata_path: Optional[str]
    rerun_mode: Optional[str]
    poll_interval: float
    verbose: bool
    check_updates: bool


class LogLine(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class SessionStatus(Message):
    def __init__(self, text: str, style: str = "") -> None:
        super().__init__()
        self.text = text
        self.style = style


class PassCompleted(Message):
    def __init__(self, pass_number: int, result: Any) -> None:
        super().__init__()
        self.pass_number = pass_number
        self.result = result


class SessionFailed(Message):
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class SessionFinished(Message):
    pass


class TextualLogHandler(logging.Handler):
    """Forward normal umadump log records to the Textual event queue."""

    def __init__(self, app: App[Any]) -> None:
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.app.post_message(LogLine(self.format(record)))
        except Exception:
            self.handleError(record)


EXPORT_LABELS = {
    "support_cards": "Support cards",
    "trained_chara_data": "Veterans",
    "card_data": "Character cards",
    "friend_data": "Friends",
    "trophy_data": "Trophies",
    "team_stadium_replay": "Team Stadium replay",
    "race_info_replay": "Current race replay",
    "idle_single_mode": "Independent Training",
}

STATUS_LABELS = {
    "written": "Written",
    "unchanged": "Unchanged",
    "unavailable": "Unavailable",
    "empty": "No data",
    "transient": "Retry later",
    "error": "Error",
}


class UmadumpApp(App[None]):
    """Small dashboard around the existing synchronous extraction engine."""

    TITLE = f"umadump {CURRENT_VERSION}"
    SUB_TITLE = "Uma Musume data exporter"

    CSS = """
    Screen {
        background: $surface;
    }

    #body {
        height: 1fr;
        padding: 1 2;
    }

    #summary {
        height: auto;
        padding: 0 1 1 1;
        border: round $primary;
    }

    .summary-row {
        height: 1;
    }

    .summary-label {
        width: 16;
        color: $text-muted;
    }

    #controls {
        height: auto;
        margin-top: 1;
    }

    #mode {
        width: 24;
        margin-right: 1;
    }

    #poll-label {
        width: 15;
        height: 3;
        content-align: right middle;
        padding-right: 1;
        color: $text-muted;
    }

    #poll-interval {
        width: 12;
        margin-right: 1;
    }

    Button {
        margin-right: 1;
    }

    #exports {
        height: 13;
        margin-top: 1;
        border: round $primary;
    }

    #log {
        height: 1fr;
        min-height: 8;
        margin-top: 1;
        padding: 0 1;
        border: round $primary;
        background: $panel;
    }

    #status.running {
        color: $warning;
    }

    #status.success {
        color: $success;
    }

    #status.warning {
        color: $warning;
    }

    #status.error {
        color: $error;
    }
    """

    BINDINGS = [
        ("ctrl+r", "start", "Start"),
        ("ctrl+s", "stop", "Stop"),
        ("ctrl+l", "clear_log", "Clear log"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, session_factory: SessionFactory, options: TuiOptions) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.options = options
        self._stop_event = threading.Event()
        self._active_worker: Optional[Worker[Any]] = None
        self._log_handler: Optional[TextualLogHandler] = None
        self._quit_when_finished = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            with Vertical(id="summary"):
                with Horizontal(classes="summary-row"):
                    yield Label("Source", classes="summary-label")
                    yield Static(self.options.minidump or "Running game process", id="source")
                with Horizontal(classes="summary-row"):
                    yield Label("Metadata", classes="summary-label")
                    yield Static(self.options.metadata_path or "Auto-detect from game", id="metadata")
                with Horizontal(classes="summary-row"):
                    yield Label("Output", classes="summary-label")
                    yield Static(str(Path.cwd()), id="output")
                with Horizontal(classes="summary-row"):
                    yield Label("Status", classes="summary-label")
                    yield Static("Ready", id="status")
            with Horizontal(id="controls"):
                mode_options = (("Run once", "once"),) if self.options.minidump else (
                    ("Run once", "once"), ("Daemon", "daemon"))
                yield Select(
                        mode_options,
                        value="daemon" if self.options.rerun_mode == "daemon" else "once",
                        allow_blank=False,
                        id="mode",
                )
                yield Label("Poll seconds", id="poll-label")
                yield Input(str(self.options.poll_interval), placeholder="Seconds", id="poll-interval")
                yield Button("Start", variant="success", id="start")
                yield Button("Stop", variant="warning", id="stop", disabled=True)
                yield Button("Clear log", id="clear-log")
            yield DataTable(id="exports", cursor_type="row", zebra_stripes=True)
            yield RichLog(id="log", markup=False, wrap=True, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#exports", DataTable)
        table.add_column("Export", key="export")
        table.add_column("Status", key="status", width=14)
        table.add_column("Details", key="details", width=70)
        for key, label in EXPORT_LABELS.items():
            table.add_row(label, "Waiting", "", key=key)

        self._log_handler = TextualLogHandler(self)
        self._log_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.handlers.clear()
        logger.addHandler(self._log_handler)
        logger.setLevel(logging.DEBUG if self.options.verbose else logging.INFO)
        logger.propagate = False
        logger.info("umadump %s interactive interface ready", CURRENT_VERSION)
        logger.info("Output directory: %s", Path.cwd())

    def on_unmount(self) -> None:
        self._stop_event.set()
        if self._log_handler is not None:
            logger.removeHandler(self._log_handler)

    def action_start(self) -> None:
        self._start_session()

    async def action_quit(self) -> None:
        if self._active_worker is not None and self._active_worker.is_running:
            self._quit_when_finished = True
            self._request_stop()
            logger.info("Waiting for the current memory operation to stop before exiting")
            return
        self.exit()

    def action_stop(self) -> None:
        self._request_stop()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self._start_session()
        elif event.button.id == "stop":
            self._request_stop()
        elif event.button.id == "clear-log":
            self.action_clear_log()

    def _start_session(self) -> None:
        if self._active_worker is not None and self._active_worker.is_running:
            return

        poll_input = self.query_one("#poll-interval", Input)
        try:
            poll_interval = float(poll_input.value)
            if poll_interval <= 0:
                raise ValueError
        except ValueError:
            self._set_status("Poll interval must be greater than zero", "error")
            poll_input.focus()
            return

        mode = str(self.query_one("#mode", Select).value)
        if self.options.minidump and mode == "daemon":
            self._set_status("Daemon mode is not available for minidumps", "error")
            return

        self._stop_event.clear()
        self._quit_when_finished = False
        self.query_one("#start", Button).disabled = True
        self.query_one("#stop", Button).disabled = False
        self._set_status("Initializing memory reader…", "running")
        self._active_worker = self._run_dump_session(mode, poll_interval)

    def _request_stop(self) -> None:
        if self._active_worker is None or not self._active_worker.is_running:
            return
        self._stop_event.set()
        self._set_status("Stopping after the current operation…", "running")

    @work(thread=True, exclusive=True, group="dump-session", exit_on_error=False)
    def _run_dump_session(self, mode: str, poll_interval: float) -> None:
        worker = get_current_worker()

        def cancel_requested() -> bool:
            return worker.is_cancelled or self._stop_event.is_set()
        self.post_message(SessionStatus("Initializing memory reader…", "running"))
        try:
            if self.options.check_updates:
                update = check_for_updates(CURRENT_VERSION)
                if update is not None:
                    logger.info("Update available: %s — %s", update.latest_version, update.download_url)
            if cancel_requested():
                raise InterruptedError("Extraction cancelled")

            with self.session_factory(
                    self.options.minidump, self.options.metadata_path, cancel_requested) as session:
                pass_number = 1
                while not worker.is_cancelled and not self._stop_event.is_set():
                    if not session.is_alive():
                        logger.info("Target process has exited")
                        break
                    self.post_message(SessionStatus(f"Running extraction pass {pass_number}…", "running"))
                    result = session.run_pass()
                    self.post_message(PassCompleted(pass_number, result))
                    if mode != "daemon":
                        break
                    pass_number += 1
                    if self._stop_event.wait(poll_interval):
                        break
        except InterruptedError:
            logger.info("Interactive dump session stopped")
        except Exception as exc:
            logger.exception("Interactive dump session failed")
            self.post_message(SessionFailed(str(exc)))
        finally:
            self.post_message(SessionFinished())

    def on_log_line(self, message: LogLine) -> None:
        self.query_one("#log", RichLog).write(message.text)

    def on_session_status(self, message: SessionStatus) -> None:
        self._set_status(message.text, message.style)

    def on_pass_completed(self, message: PassCompleted) -> None:
        result = message.result
        for extractor in result.extractors:
            status = STATUS_LABELS.get(extractor.status, extractor.status)
            details = self._extractor_details(extractor)
            self.query_one("#exports", DataTable).update_cell(extractor.name, "status", status)
            self.query_one("#exports", DataTable).update_cell(extractor.name, "details", details)
        statuses = {extractor.status for extractor in result.extractors}
        if "error" in statuses:
            summary = f"Pass {message.pass_number} completed with errors"
            style = "error"
        elif "transient" in statuses:
            summary = f"Pass {message.pass_number} completed; transient data will retry"
            style = "warning"
        else:
            summary = f"Pass {message.pass_number} completed in {result.elapsed_seconds:.2f} seconds"
            style = "success"
        self._set_status(summary, style)

    def on_session_failed(self, message: SessionFailed) -> None:
        self._set_status(message.error or "Extraction failed", "error")

    def on_session_finished(self, _message: SessionFinished) -> None:
        self.query_one("#start", Button).disabled = False
        self.query_one("#stop", Button).disabled = True
        status = self.query_one("#status", Static)
        if "error" not in status.classes and self._stop_event.is_set():
            self._set_status("Stopped", "")
        self._active_worker = None
        if self._quit_when_finished:
            self.exit()

    @staticmethod
    def _extractor_details(extractor: Any) -> str:
        if extractor.error:
            return str(extractor.error)
        if extractor.output_paths:
            paths = ", ".join(str(path) for path in extractor.output_paths)
            if extractor.item_count is not None:
                return f"{extractor.item_count} item(s) — {paths}"
            return paths
        if extractor.item_count is not None:
            return f"{extractor.item_count} item(s)"
        return ""

    def _set_status(self, text: str, style: str) -> None:
        status = self.query_one("#status", Static)
        status.update(text)
        status.remove_class("running", "success", "warning", "error")
        if style:
            status.add_class(style)


def run_tui(
        session_factory: SessionFactory,
        minidump: Optional[str],
        metadata_path: Optional[str],
        rerun_mode: Optional[str],
        poll_interval: float,
        verbose: bool,
        check_updates: bool) -> None:
    options = TuiOptions(
            minidump=minidump,
            metadata_path=metadata_path,
            rerun_mode=rerun_mode,
            poll_interval=poll_interval,
            verbose=verbose,
            check_updates=check_updates,
    )
    UmadumpApp(session_factory, options).run()
