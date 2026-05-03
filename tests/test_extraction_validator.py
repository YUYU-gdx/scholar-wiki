from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


_VALIDATOR_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "validator.py"
_VALIDATOR_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_validator", _VALIDATOR_PATH)
if _VALIDATOR_SPEC is None or _VALIDATOR_SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_VALIDATOR_PATH}")
_VALIDATOR_MOD = importlib.util.module_from_spec(_VALIDATOR_SPEC)
sys.modules[_VALIDATOR_SPEC.name] = _VALIDATOR_MOD
_VALIDATOR_SPEC.loader.exec_module(_VALIDATOR_MOD)

_REVIEW_QUEUE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "extraction" / "review_queue.py"
_REVIEW_QUEUE_SPEC = importlib.util.spec_from_file_location("smj_pipeline_extraction_review_queue", _REVIEW_QUEUE_PATH)
if _REVIEW_QUEUE_SPEC is None or _REVIEW_QUEUE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_REVIEW_QUEUE_PATH}")
_REVIEW_QUEUE_MOD = importlib.util.module_from_spec(_REVIEW_QUEUE_SPEC)
sys.modules[_REVIEW_QUEUE_SPEC.name] = _REVIEW_QUEUE_MOD
_REVIEW_QUEUE_SPEC.loader.exec_module(_REVIEW_QUEUE_MOD)

validate_relation_records = _VALIDATOR_MOD.validate_relation_records
build_review_queue = _REVIEW_QUEUE_MOD.build_review_queue
write_review_queue_csv = _REVIEW_QUEUE_MOD.write_review_queue_csv
write_review_queue_jsonl = _REVIEW_QUEUE_MOD.write_review_queue_jsonl


class ExtractionValidatorTest(unittest.TestCase):
    def test_accepts_valid_direct_effect(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p1",
                    "source": "A",
                    "target": "B",
                    "effect_form": "positive",
                    "theory_name": "RBV",
                    "verification": "supported",
                    "evidence_text": "H1 results",
                }
            ]
        )
        self.assertEqual(len(result.accepted_records), 1)
        self.assertEqual(result.rejected_records, [])

    def test_rejects_invalid_fields(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p2",
                    "source": "A",
                    "target": "B",
                    "effect_form": "sideways",
                    "verification": "partially_supported",
                    "evidence_text": " ",
                }
            ]
        )
        self.assertEqual(result.accepted_records, [])
        self.assertIn("MISSING_EVIDENCE_TEXT", result.rejected_records[0].reason_codes)
        self.assertIn("INVALID_EFFECT_FORM", result.rejected_records[0].reason_codes)

    def test_builds_review_queue_and_writes_jsonl_and_csv(self) -> None:
        validation_result = validate_relation_records(
            [
                {
                    "paper_id": "p5",
                    "source": "A",
                    "target": "C",
                    "effect_form": "invalid",
                    "verification": "supported",
                    "evidence_text": "Results text",
                },
            ]
        )

        queue = build_review_queue(validation_result.rejected_records)
        self.assertEqual(queue.total_items, 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "review.jsonl"
            csv_path = Path(tmpdir) / "review.csv"

            write_review_queue_jsonl(queue, jsonl_path)
            write_review_queue_csv(queue, csv_path)

            jsonl_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(jsonl_lines), 1)
            self.assertIn("INVALID_EFFECT_FORM", jsonl_lines[0])

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["source"], "A")
            self.assertEqual(rows[0]["target"], "C")


if __name__ == "__main__":
    unittest.main()
