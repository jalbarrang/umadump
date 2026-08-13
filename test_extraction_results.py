from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from main import ExtractionRunState, Extractor, _run_extractor


@dataclass(frozen=True)
class FakeExtractionData:
    revision: int

    def fingerprint(self) -> tuple[object, ...]:
        return ("fake", self.revision)


class ExtractionResultTests(unittest.TestCase):
    def test_reports_written_output_and_skips_unchanged_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "output.json"
            extractor = Extractor[object, FakeExtractionData, object](
                    name="fake",
                    resolve=lambda _input: FakeExtractionData(1),
                    extract=lambda _data: [{"id": 1}, {"id": 2}],
                    output_path=output_path,
            )
            state = ExtractionRunState()

            first = _run_extractor(extractor, object(), state)
            second = _run_extractor(extractor, object(), state)

            self.assertEqual(first.status, "written")
            self.assertEqual(first.item_count, 2)
            self.assertEqual(first.output_paths, (output_path,))
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), [{"id": 1}, {"id": 2}])
            self.assertEqual(second.status, "unchanged")

    def test_reports_unavailable_data(self) -> None:
        extractor = Extractor[object, FakeExtractionData, object](
                name="fake",
                resolve=lambda _input: None,
                extract=lambda _data: [],
                output_path=Path("unused.json"),
        )

        result = _run_extractor(extractor, object(), None)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.output_paths, ())


if __name__ == "__main__":
    unittest.main()
