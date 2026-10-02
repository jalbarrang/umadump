"""Background worker that drives the existing umadump extraction pipeline."""
from __future__ import annotations

import gc
import os
import queue
import threading
from pathlib import Path
from typing import Any

# The orchestration helpers still live in main.py; reuse them so the GUI and the
# CLI stay on exactly the same code path instead of duplicating the pipeline.
import main as umadump_main
from app.log_bridge import FailedEvent, FinishedEvent, GuiEvent, StateEvent
from il2cpp_runtime import build_resolver, setup_memory
from logger import logger
from update_check import CURRENT_VERSION, notify_if_update_available


class ExtractionWorker(threading.Thread):
    """Runs one of three jobs off the render thread: validate, one pass, or daemon.

    Dear PyGui may only be touched from the main thread, so results are pushed
    onto *events* — the same queue the log handler writes to — and rendered on
    the next frame.
    """

    def __init__(
        self,
        events: queue.Queue[GuiEvent],
        *,
        mode: str,
        minidump: str | None = None,
        metadata_path: str | None = None,
        output_dir: str | None = None,
        poll_interval: float = 2.0,
        verbose: bool = False,
        update_check: bool = True,
        validate_only: bool = False,
    ) -> None:
        super().__init__(name="umadump-worker", daemon=True)
        self._events = events
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

    # -- thread entry ------------------------------------------------------
    def run(self) -> None:
        previous_cwd = Path.cwd()
        try:
            if self.output_dir:
                out = Path(self.output_dir)
                out.mkdir(parents=True, exist_ok=True)
                os.chdir(out)

            logger.info("umadump %s", CURRENT_VERSION)
            if self.update_check:
                notify_if_update_available(CURRENT_VERSION)

            self._events.put(StateEvent("Opening memory backend…"))
            setup = setup_memory(self.minidump, self.metadata_path)
            logger.info("Metadata path: %s", setup.metadata_path)

            with setup.mem:
                self._events.put(StateEvent("Resolving IL2CPP runtime & validating schemas…"))
                try:
                    resolver = build_resolver(setup.mem, setup.metadata_path)
                finally:
                    setup.mem.clear_cache()
                    gc.collect()

                if self.validate_only:
                    logger.info("Schema validation finished successfully")
                    self._events.put(FinishedEvent("Schema validation passed"))
                    return

                self._events.put(StateEvent("Resolving singletons…"))
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

                self._events.put(StateEvent("Running extractors…"))
                elapsed = umadump_main._run_extractor_pass(
                    setup.mem, resolver, singleton_index, roots, umadump_main.ExtractionRunState()
                )
                logger.info("Extractor pass completed in %.2fs", elapsed)
                self._events.put(FinishedEvent(f"Extractor pass completed in {elapsed:.2f}s"))
        except Exception as exc:  # noqa: BLE001 - surface anything to the GUI
            logger.exception("Run failed")
            self._events.put(FailedEvent(f"{type(exc).__name__}: {exc}"))
        finally:
            try:
                os.chdir(previous_cwd)
            except OSError:
                pass

    # -- daemon loop -------------------------------------------------------
    def _run_daemon(self, setup: Any, resolver: Any, singleton_index: Any, roots: Any) -> None:
        if self.minidump:
            raise RuntimeError("Daemon mode requires a live process, not a minidump")

        state = umadump_main.ExtractionRunState()
        logger.info("Daemon mode started; polling every %.2fs", self.poll_interval)
        self._events.put(StateEvent("Daemon running — press Stop to finish"))
        pass_num = 1
        while not self._stop.is_set() and setup.mem.is_alive():
            elapsed = umadump_main._run_extractor_pass(setup.mem, resolver, singleton_index, roots, state)
            logger.debug("Daemon extractor pass %d completed in %.2fs", pass_num, elapsed)
            pass_num += 1
            if self._stop.wait(self.poll_interval):
                break

        if self._stop.is_set():
            logger.info("Daemon stopped by user after %d pass(es)", pass_num - 1)
            self._events.put(FinishedEvent(f"Daemon stopped after {pass_num - 1} pass(es)"))
        else:
            logger.info("Target process has exited; stopping daemon mode")
            self._events.put(FinishedEvent("Target process exited; daemon stopped"))
