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
    def test_accepts_valid_main_model_relation(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p1",
                    "source_var": "A",
                    "target_var": "B",
                    "model_tag": "main_model",
                    "direction": "positive",
                    "verification": "supported",
                    "evidence_anchor": "Results paragraph 1",
                }
            ]
        )

        self.assertEqual(len(result.accepted_records), 1)
        self.assertEqual(result.accepted_records[0]["target_var"], "B")
        self.assertEqual(result.rejected_records, [])

    def test_rejects_relation_without_evidence_anchor(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p2",
                    "source_var": "A",
                    "target_var": "B",
                    "model_tag": "main_model",
                    "direction": "positive",
                    "verification": "supported",
                    "evidence_anchor": "   ",
                }
            ]
        )

        self.assertEqual(result.accepted_records, [])
        self.assertEqual(result.rejected_records[0].reason_codes, ["MISSING_EVIDENCE_ANCHOR"])
        self.assertEqual(result.rejected_records[0].record["paper_id"], "p2")

    def test_rejects_invalid_model_direction_and_verification(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p3",
                    "source_var": "A",
                    "target_var": "B",
                    "model_tag": "robustness",
                    "direction": "sideways",
                    "verification": "unclear",
                    "evidence_anchor": "Table 2",
                }
            ]
        )

        self.assertEqual(result.accepted_records, [])
        self.assertEqual(
            result.rejected_records[0].reason_codes,
            ["INVALID_MODEL_TAG", "INVALID_DIRECTION", "INVALID_VERIFICATION"],
        )

    def test_builds_review_queue_and_writes_jsonl_and_csv(self) -> None:
        validation_result = validate_relation_records(
            [
                {
                    "paper_id": "p4",
                    "source_var": "A",
                    "target_var": "B",
                    "model_tag": "main_model",
                    "direction": "positive",
                    "verification": "supported",
                    "evidence_anchor": "Results",
                },
                {
                    "paper_id": "p5",
                    "source_var": "A",
                    "target_var": "C",
                    "model_tag": "secondary_model",
                    "direction": "negative",
                    "verification": "supported",
                    "evidence_anchor": "Table 3",
                },
            ]
        )

        queue = build_review_queue(validation_result.rejected_records)

        self.assertEqual(queue.total_items, 1)
        self.assertEqual(queue.items[0].reason_codes, ["INVALID_MODEL_TAG"])
        self.assertEqual(queue.items[0].record["paper_id"], "p5")

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "review.jsonl"
            csv_path = Path(tmpdir) / "review.csv"

            write_review_queue_jsonl(queue, jsonl_path)
            write_review_queue_csv(queue, csv_path)

            jsonl_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(jsonl_lines), 1)
            self.assertEqual(
                json.loads(jsonl_lines[0]),
                {
                    "reason_codes": ["INVALID_MODEL_TAG"],
                    "record": {
                        "direction": "negative",
                        "evidence_anchor": "Table 3",
                        "model_tag": "secondary_model",
                        "paper_id": "p5",
                        "source_var": "A",
                        "target_var": "C",
                        "verification": "supported",
                    },
                },
            )

            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(
                rows,
                [
                    {
                        "reason_codes": "INVALID_MODEL_TAG",
                        "paper_id": "p5",
                        "source_var": "A",
                        "target_var": "C",
                        "model_tag": "secondary_model",
                        "direction": "negative",
                        "verification": "supported",
                        "evidence_anchor": "Table 3",
                    }
                ],
            )

    def test_rejects_abbreviation_primary_name_without_unresolved_flag(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p6",
                    "source_var": "TMT",
                    "target_var": "Firm performance",
                    "model_tag": "main_model",
                    "direction": "positive",
                    "verification": "supported",
                    "evidence_anchor": "Results",
                }
            ]
        )
        self.assertEqual(result.accepted_records, [])
        self.assertIn("ABBR_AS_PRIMARY_NAME", result.rejected_records[0].reason_codes)

    def test_rejects_unresolved_abbreviation_without_abbr_form(self) -> None:
        result = validate_relation_records(
            [
                {
                    "paper_id": "p7",
                    "source_var": "TMT",
                    "target_var": "Firm performance",
                    "model_tag": "main_model",
                    "direction": "positive",
                    "verification": "supported",
                    "evidence_anchor": "Results",
                    "unresolved_abbr": True,
                    "abbr_form": " ",
                }
            ]
        )
        self.assertEqual(result.accepted_records, [])
        self.assertIn("MISSING_ABBR_FORM", result.rejected_records[0].reason_codes)


if __name__ == "__main__":
    unittest.main()
