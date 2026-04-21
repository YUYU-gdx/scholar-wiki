from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "literature" / "dataset_tools.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_literature_dataset_tools", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

build_base_dataset = _MOD.build_base_dataset
estimate_embedding_cost = _MOD.estimate_embedding_cost
normalize_doi = _MOD.normalize_doi
summarize_db_fulltext = _MOD.summarize_db_fulltext
safe_float = _MOD._safe_float
normalize_reject_reason = _MOD._normalize_reject_reason


class LiteratureDatasetToolsTest(unittest.TestCase):
    def test_normalize_doi_strips_url_prefix(self) -> None:
        self.assertEqual(normalize_doi("https://doi.org/10.1002/smj.123"), "10.1002/smj.123")
        self.assertEqual(normalize_doi(" DOI: 10.1002/SMJ.123 "), "10.1002/smj.123")

    def test_build_base_dataset_filters_empty_garbled_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            ok_txt = tmp / "ok.txt"
            ok_txt.write_text("This is an empirical paper. It has usable content.", encoding="utf-8")
            dup_txt = tmp / "dup.txt"
            dup_txt.write_text("Another non-empty paper text.", encoding="utf-8")
            empty_txt = tmp / "empty.txt"
            empty_txt.write_text("", encoding="utf-8")
            garbled_txt = tmp / "garbled.txt"
            garbled_txt.write_text("锟斤拷锟斤拷������", encoding="utf-8")

            manifest_path = tmp / "manifest.jsonl"
            rows = [
                {"paper_id": "p1", "doi": "10.1002/a", "source_path": str(ok_txt)},
                {"paper_id": "p2", "doi": "10.1002/A", "source_path": str(dup_txt)},
                {"paper_id": "p3", "doi": "10.1002/b", "source_path": str(empty_txt)},
                {"paper_id": "p4", "doi": "10.1002/c", "source_path": str(garbled_txt)},
            ]
            manifest_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

            out_dir = tmp / "out"
            result = build_base_dataset(
                manifest_path=manifest_path,
                output_dir=out_dir,
                garble_threshold=0.02,
            )

            self.assertEqual(result["total_rows"], 4)
            self.assertEqual(result["base_rows"], 1)
            self.assertEqual(result["rejected_rows"], 3)

            base_path = out_dir / "base_dataset.jsonl"
            rej_path = out_dir / "rejected_dataset.jsonl"
            self.assertTrue(base_path.exists())
            self.assertTrue(rej_path.exists())
            base_lines = [x for x in base_path.read_text(encoding="utf-8").splitlines() if x.strip()]
            rej_lines = [x for x in rej_path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(base_lines), 1)
            self.assertEqual(len(rej_lines), 3)

    def test_estimate_embedding_cost_returns_budget_fields(self) -> None:
        report = estimate_embedding_cost(total_tokens=1_250_000, cny_per_million_tokens=2.0, budget_cny=100.0)
        self.assertIn("estimated_cost_cny", report)
        self.assertIn("budget_cny", report)
        self.assertIn("within_budget", report)
        self.assertTrue(report["within_budget"])

    def test_summarize_db_fulltext(self) -> None:
        mysql_payload = {
            "engine": "mysql",
            "candidate_columns": [
                {"schema": "a", "table": "papers", "column": "full_text", "non_empty_rows": 10, "total_rows": 10}
            ],
        }
        pg_payload = {"engine": "postgres", "status": "skipped", "reason": "dsn_missing"}
        summary = summarize_db_fulltext(mysql_payload, pg_payload)
        self.assertIn("mysql", summary)
        self.assertIn("postgres", summary)
        self.assertIn("has_fulltext_candidate", summary["mysql"])

    def test_safe_float_handles_null(self) -> None:
        self.assertEqual(safe_float("NULL"), 0.0)
        self.assertEqual(safe_float(""), 0.0)
        self.assertEqual(safe_float(None), 0.0)
        self.assertEqual(safe_float("1.5"), 1.5)

    def test_normalize_reject_reason(self) -> None:
        self.assertEqual(normalize_reject_reason("source_too_large:123"), "source_too_large")
        self.assertEqual(normalize_reject_reason("mineru_not_installed:mineru"), "pdf_mineru_unavailable")


if __name__ == "__main__":
    unittest.main()
