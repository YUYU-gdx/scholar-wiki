from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "run_extraction_mvp.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_run_extraction_mvp", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

run = _MOD.run
RunSummary = _MOD.RunSummary


class _QualifierResult:
    def __init__(self, doc_class: str) -> None:
        self.doc_class = doc_class


class RunExtractionMvpTest(unittest.TestCase):
    def test_run_collects_only_class_a_and_excludes_class_b_from_denominator(self) -> None:
        manifest_rows = [
            {"paper_id": "b-1", "html": "class-b"},
            {"paper_id": "a-1", "html": "class-a-1"},
            {"paper_id": "c-1", "html": "class-c"},
            {"paper_id": "b-2", "html": "class-b"},
            {"paper_id": "a-2", "html": "class-a-2"},
            {"paper_id": "a-3", "html": "class-a-3"},
        ]
        classifications = {
            "class-b": _QualifierResult("B"),
            "class-a-1": _QualifierResult("A"),
            "class-c": _QualifierResult("C"),
            "class-a-2": _QualifierResult("A"),
            "class-a-3": _QualifierResult("A"),
        }
        processed_ids: list[str] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.jsonl"
            manifest_path.write_text(
                "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in manifest_rows),
                encoding="utf-8",
            )

            with patch.object(
                _MOD,
                "classify_document",
                side_effect=lambda html: classifications[html],
            ), patch.object(
                _MOD,
                "_process_class_a_record",
                side_effect=lambda row: processed_ids.append(row["paper_id"]),
            ):
                summary = run(manifest_path, sample_size=2)

        self.assertEqual(processed_ids, ["a-1", "a-2"])
        self.assertEqual(
            summary,
            RunSummary(
                seen=5,
                class_a_used=2,
                class_b_skipped=2,
                class_c_skipped=1,
                denominator_used=3,
            ),
        )

    def test_run_stops_once_sample_size_of_class_a_is_reached(self) -> None:
        manifest_rows = [
            {"paper_id": "a-1", "html": "class-a-1"},
            {"paper_id": "b-1", "html": "class-b"},
            {"paper_id": "a-2", "html": "class-a-2"},
            {"paper_id": "a-3", "html": "class-a-3"},
        ]
        classifications = {
            "class-a-1": _QualifierResult("A"),
            "class-b": _QualifierResult("B"),
            "class-a-2": _QualifierResult("A"),
            "class-a-3": _QualifierResult("A"),
        }
        processed_ids: list[str] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.jsonl"
            manifest_path.write_text(
                "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in manifest_rows),
                encoding="utf-8",
            )

            with patch.object(
                _MOD,
                "classify_document",
                side_effect=lambda html: classifications[html],
            ), patch.object(
                _MOD,
                "_process_class_a_record",
                side_effect=lambda row: processed_ids.append(row["paper_id"]),
            ):
                summary = run(manifest_path, sample_size=2)

        self.assertEqual(processed_ids, ["a-1", "a-2"])
        self.assertEqual(summary.seen, 3)
        self.assertEqual(summary.class_a_used, 2)
        self.assertEqual(summary.class_b_skipped, 1)
        self.assertEqual(summary.class_c_skipped, 0)
        self.assertEqual(summary.denominator_used, 2)


if __name__ == "__main__":
    unittest.main()
