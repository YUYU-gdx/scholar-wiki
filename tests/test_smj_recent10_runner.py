from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
import tempfile

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "smj_recent10_runner.py"
_SPEC = importlib.util.spec_from_file_location("smj_recent10_runner", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

is_pdf_bytes = _MOD.is_pdf_bytes
pick_date = _MOD.pick_date
safe_name = _MOD.safe_name
wiley_pdf_candidates = _MOD.wiley_pdf_candidates
normalize_doi = _MOD.normalize_doi
load_works_from_csv = _MOD.load_works_from_csv
shard_for_doi = _MOD.shard_for_doi
save_works_csv = _MOD.save_works_csv
SmjWork = _MOD.SmjWork


class SmjRecent10RunnerTest(unittest.TestCase):
    def test_pick_date_prefers_published_print(self) -> None:
        item = {
            "published-print": {"date-parts": [[2024, 9, 3]]},
            "issued": {"date-parts": [[2024, 8, 1]]},
        }
        self.assertEqual(pick_date(item), "2024-09-03")

    def test_is_pdf_bytes_works_for_header_or_signature(self) -> None:
        self.assertTrue(is_pdf_bytes(b"%PDF-1.7\n...", "application/octet-stream"))
        self.assertTrue(is_pdf_bytes(b"random", "application/pdf"))
        self.assertFalse(is_pdf_bytes(b"<html>blocked</html>", "text/html"))

    def test_safe_name(self) -> None:
        self.assertEqual(safe_name("10.1002/smj.70081"), "10.1002_smj.70081")

    def test_wiley_pdf_candidates(self) -> None:
        doi = "10.1002/smj.70081"
        out = wiley_pdf_candidates(doi)
        self.assertEqual(out[0], f"https://sms.onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true")
        self.assertTrue(any("/doi/pdf/" in x for x in out))

    def test_normalize_doi(self) -> None:
        self.assertEqual(normalize_doi(" 10.1002/SMJ.70081 "), "10.1002/smj.70081")

    def test_load_works_from_csv(self) -> None:
        content = "doi,title,pub_date,article_url\n10.1002/SMJ.70081,T1,2026-01-01,\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "in.csv"
            p.write_text(content, encoding="utf-8")
            rows = load_works_from_csv(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].doi, "10.1002/smj.70081")
        self.assertIn("/doi/full/10.1002/smj.70081", rows[0].article_url)

    def test_shard_for_doi_is_stable(self) -> None:
        doi = "10.1002/smj.70081"
        a = shard_for_doi(doi, 4)
        b = shard_for_doi(doi, 4)
        self.assertEqual(a, b)
        self.assertTrue(0 <= a < 4)

    def test_save_and_load_works_csv_roundtrip(self) -> None:
        works = [SmjWork(doi="10.1002/smj.1", title="T", pub_date="2026-01-01", article_url="https://x")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "works.csv"
            save_works_csv(p, works)
            rows = load_works_from_csv(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].doi, "10.1002/smj.1")


if __name__ == "__main__":
    unittest.main()
