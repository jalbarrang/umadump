"""Bridge the ``umadump`` logger into a thread-safe queue the GUI drains.

Dear PyGui is immediate-mode and must be driven from the main thread, so the
worker thread never touches it. Everything the worker wants to show is pushed
here as an event and rendered on the next frame.
"""
from __future__ import annotations

import logging
import queue
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogEvent:
    """One formatted log line plus its ``logging`` level number."""

    text: str
    level: int


@dataclass(frozen=True, slots=True)
class StateEvent:
    """Short status text for the current phase."""

    text: str


@dataclass(frozen=True, slots=True)
class FinishedEvent:
    """A run finished successfully; *summary* is human-readable."""

    summary: str


@dataclass(frozen=True, slots=True)
class FailedEvent:
    """A run raised; *message* is the formatted exception."""

    message: str


GuiEvent = LogEvent | StateEvent | FinishedEvent | FailedEvent


class QueueLogHandler(logging.Handler):
    """Forward formatted records to *events* instead of writing them anywhere."""

    def __init__(self, events: queue.Queue[GuiEvent]) -> None:
        super().__init__()
        self._events = events
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._events.put(LogEvent(self.format(record), record.levelno))
        except Exception:  # noqa: BLE001 - never let logging blow up the worker
            self.handleError(record)


def install_queue_logging(events: queue.Queue[GuiEvent], verbose: bool) -> QueueLogHandler:
    """Replace the umadump logger handlers with a single queue-backed handler."""

    from logger import logger

    handler = QueueLogHandler(events)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    return handler
