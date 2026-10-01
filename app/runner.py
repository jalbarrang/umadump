"""Background worker that drives the existing umadump extraction pipeline."""
from __future__ import annotations

import gc
import os
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from il2cpp_runtime import build_resolver, setup_memory
from logger import logger
from update_check import CURRENT_VERSION, notify_if_update_available

# The orchestration helpers still live in main.py; reuse them so the GUI and the
# CLI stay on exactly the same code path instead of duplicating the pipeline.
import main as umadump_main


class ExtractionWorker(QThread):
    """Runs one of three jobs off the GUI thread: validate, one pass, or daemon."""

    succeeded = Signal(str)  # human-readable summary
    failed = Signal(str)     # error message
    state_changed = Signal(str)  # short status text for the status bar

    def __init__(
        self,
        *,
        mode: str,
        minidump: Optional[str] = None,
        metadata_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        poll_interval: float = 2.0,
        verbose: bool = False,
        update_check: bool = True,
        validate_only: bool = False,
    ) -> None:
        super().__init__()
        self.mode = mode  # "once" | "daemon" | "validate"
        self.minidump = minidump or None
        self.metadata_path = metadata_path or None
        self.output_dir = output_dir or None
        self.poll_interval = max(0.1, float(poll_interval))
        self.verbose = verbose
        self.update_check = update_check
        self.validate_only = validate_only or mode == "validate"
        self._stop = threading.Event()

    # -- control -----------------------------------------------------------
    def request_stop(self) -> None:
        self._stop.set()

    # -- QThread entry -----------------------------------------------------
    def run(self) -> None:  # noqa: C901 - linear pipeline, kept readable on purpose
        previous_cwd = Path.cwd()
        try:
            if self.output_dir:
                out = Path(self.output_dir)
                out.mkdir(parents=True, exist_ok=True)
                os.chdir(out)

            logger.info("umadump %s", CURRENT_VERSION)
            if self.update_check:
                notify_if_update_available(CURRENT_VERSION)

            self.state_changed.emit("Opening memory backend…")
            setup = setup_memory(self.minidump, self.metadata_path)
            logger.info("Metadata path: %s", setup.metadata_path)

            with setup.mem:
                self.state_changed.emit("Resolving IL2CPP runtime & validating schemas…")
                try:
                    resolver = build_resolver(setup.mem, setup.metadata_path)
                finally:
                    setup.mem.clear_cache()
                    gc.collect()

                if self.validate_only:
                    logger.info("Schema validation finished successfully")
                    self.succeeded.emit("Schema validation passed")
                    return

                self.state_changed.emit("Resolving singletons…")
                umadump_main._prepare_memory_pass(setup.mem)
                try:
                    logger.info(
                        "Scanning %d generic class instantiations...",
                        resolver.meta_reg.genericClassesCount,
                    )
                    singleton_index = umadump_main._build_singleton_generic_index(resolver.meta_reg)
                    roots = umadump_main._init_singleton_roots()
                    umadump_main._refresh_singleton_roots(resolver, singleton_index, roots)
                finally:
                    umadump_main._finish_memory_pass(setup.mem)

                if self.mode == "daemon":
                    self._run_daemon(setup, resolver, singleton_index, roots)
                    return

                self.state_changed.emit("Running extractors…")
                elapsed = umadump_main._run_extractor_pass(
                    setup.mem, resolver, singleton_index, roots, umadump_main.ExtractionRunState()
                )
                logger.info("Extractor pass completed in %.2fs", elapsed)
                self.succeeded.emit(f"Extractor pass completed in {elapsed:.2f}s")
        except Exception as exc:  # noqa: BLE001 - surface anything to the GUI
            logger.exception("Run failed")
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            try:
                os.chdir(previous_cwd)
            except OSError:
                pass

    # -- daemon loop -------------------------------------------------------
    def _run_daemon(self, setup, resolver, singleton_index, roots) -> None:
        if self.minidump:
            raise RuntimeError("Daemon mode requires a live process, not a minidump")

        state = umadump_main.ExtractionRunState()
        logger.info("Daemon mode started; polling every %.2fs", self.poll_interval)
        self.state_changed.emit("Daemon running — press Stop to finish")
        pass_num = 1
        while not self._stop.is_set() and setup.mem.is_alive():
            elapsed = umadump_main._run_extractor_pass(setup.mem, resolver, singleton_index, roots, state)
            logger.debug("Daemon extractor pass %d completed in %.2fs", pass_num, elapsed)
            pass_num += 1
            if self._stop.wait(self.poll_interval):
                break

        if self._stop.is_set():
            logger.info("Daemon stopped by user after %d pass(es)", pass_num - 1)
            self.succeeded.emit(f"Daemon stopped after {pass_num - 1} pass(es)")
        else:
            logger.info("Target process has exited; stopping daemon mode")
            self.succeeded.emit("Target process exited; daemon stopped")
