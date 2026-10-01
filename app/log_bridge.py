"""Bridge the ``umadump`` logger into Qt signals so the GUI can show live logs."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal


class LogEmitter(QObject):
    """Re-emits log records on the GUI thread via a queued connection."""

    message = Signal(str, int)  # formatted text, logging level number


class QtLogHandler(logging.Handler):
    """A logging handler that forwards formatted records to a :class:`LogEmitter`."""

    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self._emitter = emitter
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emitter.message.emit(self.format(record), record.levelno)
        except Exception:  # pragma: no cover - never let logging blow up the worker
            self.handleError(record)


def install_qt_logging(emitter: LogEmitter, verbose: bool) -> QtLogHandler:
    """Replace the umadump logger handlers with a single Qt-backed handler."""

    from logger import logger

    handler = QtLogHandler(emitter)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    return handler
