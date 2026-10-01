"""Main window: source configuration, run controls, and a live log console."""
from __future__ import annotations

import html
import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from logger import logger

from app.log_bridge import LogEmitter
from app.runner import ExtractionWorker

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_output_dir() -> Path:
    """Default dump location.

    In a PyInstaller bundle ``__file__`` lives under ``_internal/``, so deriving a
    default from it would write JSON *inside* the app's own install directory.
    Frozen builds therefore default to a sibling folder next to the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "umadump-dumps"
    return PROJECT_ROOT

_LEVEL_COLORS = {
    logging.DEBUG: "#8a8a8a",
    logging.INFO: "#d8d8d8",
    logging.WARNING: "#e0a030",
    logging.ERROR: "#e05c5c",
    logging.CRITICAL: "#ff4d4d",
}


class MainWindow(QMainWindow):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self.setWindowTitle("umadump — extractor console")
        self.resize(980, 720)
        self._worker: Optional[ExtractionWorker] = None
        self._settings = QSettings("umadump", "umadump-gui")
        self._default_output_dir = _default_output_dir()

        self._build_ui(emitter)
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _build_ui(self, emitter: LogEmitter) -> None:
        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        root_layout.addWidget(self._build_source_group())
        root_layout.addWidget(self._build_run_group())
        root_layout.addWidget(self._build_log_group(emitter), stretch=1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Idle")

        self._apply_mode_state()

    def _build_source_group(self) -> QGroupBox:
        box = QGroupBox("Source")
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        mode_row = QHBoxLayout()
        self.live_radio = QRadioButton("Live process")
        self.minidump_radio = QRadioButton("Minidump")
        self.live_radio.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.live_radio)
        self._mode_group.addButton(self.minidump_radio)
        self.live_radio.toggled.connect(self._apply_mode_state)
        mode_row.addWidget(self.live_radio)
        mode_row.addWidget(self.minidump_radio)
        mode_row.addStretch(1)
        form.addRow("Mode", mode_row)

        self.minidump_edit = QLineEdit()
        self.minidump_edit.setPlaceholderText("Path to a full-memory .dmp file")
        form.addRow("Minidump", self._browse_row(self.minidump_edit, self._pick_minidump))

        self.metadata_edit = QLineEdit()
        self.metadata_edit.setPlaceholderText("Auto-derived from the game exe in live mode; required for a minidump")
        form.addRow("global-metadata.dat", self._browse_row(self.metadata_edit, self._pick_metadata))

        self.output_edit = QLineEdit(str(self._default_output_dir))
        form.addRow("Output folder", self._browse_row(self.output_edit, self._pick_output_dir))

        return box

    def _build_run_group(self) -> QGroupBox:
        box = QGroupBox("Run")
        row = QHBoxLayout(box)

        self.validate_button = QPushButton("Validate schema")
        self.once_button = QPushButton("Run once")
        self.daemon_button = QPushButton("Start daemon")
        self.validate_button.clicked.connect(lambda: self._start("validate"))
        self.once_button.clicked.connect(lambda: self._start("once"))
        self.daemon_button.clicked.connect(self._toggle_daemon)

        row.addWidget(self.validate_button)
        row.addWidget(self.once_button)
        row.addWidget(self.daemon_button)
        row.addSpacing(12)

        row.addWidget(QLabel("Poll (s)"))
        self.poll_spin = QDoubleSpinBox()
        self.poll_spin.setRange(0.1, 120.0)
        self.poll_spin.setSingleStep(0.5)
        self.poll_spin.setValue(2.0)
        self.poll_spin.setDecimals(1)
        row.addWidget(self.poll_spin)

        self.verbose_check = QCheckBox("Verbose")
        self.update_check = QCheckBox("Update check")
        self.update_check.setChecked(True)
        row.addWidget(self.verbose_check)
        row.addWidget(self.update_check)
        row.addStretch(1)

        self.open_output_button = QPushButton("Open output folder")
        self.open_output_button.clicked.connect(self._open_output_dir)
        row.addWidget(self.open_output_button)

        return box

    def _build_log_group(self, emitter: LogEmitter) -> QGroupBox:
        box = QGroupBox("Log")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        header.addStretch(1)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(lambda: self.log_view.clear())
        header.addWidget(clear_button)
        layout.addLayout(header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setStyleSheet("QPlainTextEdit { background:#1e1e1e; color:#d8d8d8; border:1px solid #3a3a3a; }")
        layout.addWidget(self.log_view)

        emitter.message.connect(self._append_log)
        return box

    def _browse_row(self, edit: QLineEdit, slot) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, stretch=1)
        button = QPushButton("Browse…")
        button.clicked.connect(slot)
        row.addWidget(button)
        return wrapper

    # -------------------------------------------------------------- actions
    def _pick_minidump(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select minidump", self.output_edit.text(),
                                              "Dump files (*.dmp);;All files (*)")
        if path:
            self.minidump_edit.setText(path)

    def _pick_metadata(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select global-metadata.dat", self.output_edit.text(),
                                              "Metadata (*.dat);;All files (*)")
        if path:
            self.metadata_edit.setText(path)

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output folder", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _open_output_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_edit.text() or str(self._default_output_dir)))

    # -------------------------------------------------------------- settings
    def _load_settings(self) -> None:
        s = self._settings
        if s.value("mode", "live", type=str) == "minidump":
            self.minidump_radio.setChecked(True)
        self.minidump_edit.setText(s.value("minidump", "", type=str))
        self.metadata_edit.setText(s.value("metadata", "", type=str))
        saved_output = s.value("output_dir", "", type=str)
        if saved_output:
            self.output_edit.setText(saved_output)
        self.poll_spin.setValue(s.value("poll_interval", 2.0, type=float))
        self.verbose_check.setChecked(s.value("verbose", False, type=bool))
        self.update_check.setChecked(s.value("update_check", True, type=bool))
        self._apply_mode_state()

    def _save_settings(self) -> None:
        s = self._settings
        s.setValue("mode", "minidump" if self.minidump_radio.isChecked() else "live")
        s.setValue("minidump", self.minidump_edit.text())
        s.setValue("metadata", self.metadata_edit.text())
        s.setValue("output_dir", self.output_edit.text())
        s.setValue("poll_interval", self.poll_spin.value())
        s.setValue("verbose", self.verbose_check.isChecked())
        s.setValue("update_check", self.update_check.isChecked())

    # -------------------------------------------------------------- cleanup
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._save_settings()
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait(5000)
        super().closeEvent(event)

    def _apply_mode_state(self) -> None:
        live = self.live_radio.isChecked()
        self.minidump_edit.parentWidget().setEnabled(not live)
        # Daemon mode only makes sense against a live process.
        self.daemon_button.setEnabled(live)
        if not live and self._worker and self._worker.mode == "daemon":
            self._worker.request_stop()

    def _toggle_daemon(self) -> None:
        if self._worker and self._worker.mode == "daemon":
            self._worker.request_stop()
            self.daemon_button.setText("Stopping…")
            self.daemon_button.setEnabled(False)
        else:
            self._start("daemon")

    def _start(self, mode: str) -> None:
        if self._worker is not None:
            return

        minidump = self.minidump_edit.text().strip()
        metadata = self.metadata_edit.text().strip()
        if not self.live_radio.isChecked():
            if not minidump:
                self._append_log("ERROR: Minidump mode needs a .dmp path.", logging.ERROR)
                return
            if not metadata:
                self._append_log("ERROR: Minidump mode needs a global-metadata.dat path.", logging.ERROR)
                return

        verbose = self.verbose_check.isChecked()
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        self._set_running(True, mode)
        worker = ExtractionWorker(
            mode=mode,
            minidump=minidump,
            metadata_path=metadata or None,
            output_dir=self.output_edit.text().strip() or str(self._default_output_dir),
            poll_interval=self.poll_spin.value(),
            verbose=verbose,
            update_check=self.update_check.isChecked(),
            validate_only=(mode == "validate"),
        )
        worker.state_changed.connect(self.statusBar().showMessage)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()

    # ------------------------------------------------------------- handlers
    def _on_success(self, summary: str) -> None:
        self._append_log(summary, logging.INFO)
        self.statusBar().showMessage(summary)

    def _on_failure(self, message: str) -> None:
        self._append_log(message, logging.ERROR)
        self.statusBar().showMessage("Failed")

    def _on_finished(self) -> None:
        self._worker = None
        self._set_running(False, None)

    def _set_running(self, running: bool, mode: Optional[str]) -> None:
        for widget in (self.live_radio, self.minidump_radio, self.minidump_edit, self.metadata_edit,
                       self.output_edit, self.validate_button, self.once_button, self.poll_spin,
                       self.verbose_check, self.update_check):
            widget.setEnabled(not running)
        if running:
            self.daemon_button.setEnabled(mode == "daemon")
            self.daemon_button.setText("Stop daemon" if mode == "daemon" else "Start daemon")
        else:
            self.daemon_button.setText("Start daemon")
            self._apply_mode_state()

    def _append_log(self, text: str, level: int) -> None:
        color = _LEVEL_COLORS.get(level, "#d8d8d8")
        safe = html.escape(text).replace("\n", "<br>")
        self.log_view.appendHtml(f'<span style="color:{color}; white-space:pre-wrap;">{safe}</span>')
