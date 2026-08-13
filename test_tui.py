from __future__ import annotations

import time
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from textual.widgets import Button, DataTable, Input, Select, Static

from tui import TuiOptions, UmadumpApp


class FakeSession:
    def __init__(
            self,
            minidump: str | None = None,
            metadata_path: str | None = None,
            cancel_requested: object | None = None) -> None:
        self.alive = True

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def run_pass(self) -> SimpleNamespace:
        extractor = SimpleNamespace(
                name="support_cards",
                status="written",
                output_paths=(Path("support_card_data.json"),),
                item_count=2,
                error=None,
        )
        return SimpleNamespace(elapsed_seconds=0.12, extractors=(extractor,))


class FakeCancelableSession(FakeSession):
    def __init__(
            self,
            minidump: str | None = None,
            metadata_path: str | None = None,
            cancel_requested: Callable[[], bool] | None = None) -> None:
        super().__init__(minidump, metadata_path, cancel_requested)
        self.cancel_requested = cancel_requested or (lambda: False)

    def run_pass(self) -> SimpleNamespace:
        while not self.cancel_requested():
            time.sleep(0.01)
        raise InterruptedError("Extraction cancelled")


class FakeErrorSession(FakeSession):
    def run_pass(self) -> SimpleNamespace:
        extractor = SimpleNamespace(
                name="support_cards",
                status="error",
                output_paths=(),
                item_count=None,
                error="synthetic failure",
        )
        return SimpleNamespace(elapsed_seconds=0.12, extractors=(extractor,))


class UmadumpAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_updates_export_table(self) -> None:
        options = TuiOptions(
                minidump=None,
                metadata_path=None,
                rerun_mode="once",
                poll_interval=2.0,
                verbose=False,
                check_updates=False,
        )
        app = UmadumpApp(FakeSession, options)

        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.click("#start")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._active_worker is None:
                    break

            status = app.query_one("#status", Static)
            exports = app.query_one("#exports", DataTable)
            self.assertEqual(str(status.content), "Pass 1 completed in 0.12 seconds")
            self.assertEqual(str(exports.get_cell("support_cards", "status")), "Written")
            self.assertIn("support_card_data.json", str(exports.get_cell("support_cards", "details")))
            self.assertFalse(app.query_one("#start", Button).disabled)

    async def test_stop_cooperatively_ends_worker(self) -> None:
        options = TuiOptions(None, None, "daemon", 2.0, False, False)
        app = UmadumpApp(FakeCancelableSession, options)

        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.click("#start")
            await pilot.pause(0.05)
            await pilot.click("#stop")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._active_worker is None:
                    break

            self.assertIsNone(app._active_worker)
            self.assertEqual(str(app.query_one("#status", Static).content), "Stopped")
            self.assertFalse(app.query_one("#start", Button).disabled)

    async def test_failed_extractor_marks_pass_as_error(self) -> None:
        options = TuiOptions(None, None, "once", 2.0, False, False)
        app = UmadumpApp(FakeErrorSession, options)

        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.click("#start")
            for _ in range(50):
                await pilot.pause(0.02)
                if app._active_worker is None:
                    break

            self.assertEqual(str(app.query_one("#status", Static).content),
                             "Pass 1 completed with errors")
            self.assertIn("error", app.query_one("#status", Static).classes)

    async def test_minidump_only_offers_run_once(self) -> None:
        options = TuiOptions("dump.dmp", "global-metadata.dat", "once", 2.0, False, False)
        app = UmadumpApp(FakeSession, options)

        async with app.run_test(size=(100, 35)):
            mode = app.query_one("#mode", Select)
            self.assertEqual(len(mode._options), 1)
            self.assertEqual(str(mode.value), "once")

    async def test_rejects_invalid_poll_interval(self) -> None:
        options = TuiOptions(None, None, "once", 2.0, False, False)
        app = UmadumpApp(FakeSession, options)

        async with app.run_test(size=(100, 35)) as pilot:
            poll_interval = app.query_one("#poll-interval", Input)
            poll_interval.value = "0"
            await pilot.click("#start")
            await pilot.pause()

            self.assertEqual(str(app.query_one("#status", Static).content),
                             "Poll interval must be greater than zero")
            self.assertIsNone(app._active_worker)


if __name__ == "__main__":
    unittest.main()
