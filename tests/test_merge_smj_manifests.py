from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "merge_smj_manifests.py"
_SPEC = importlib.util.spec_from_file_location("merge_smj_manifests", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

better_row = _MOD.better_row
merge_rows = _MOD.merge_rows


class MergeSmjManifestsTest(unittest.TestCase):
    def test_better_row_prefers_success(self) -> None:
        a = {"doi": "10.1/a", "final_status": "failed", "updated_at": "2026-03-29T01:00:00+00:00", "html_ok": "true", "pdf_ok": "false"}
        b = {"doi": "10.1/a", "final_status": "success", "updated_at": "2026-03-29T00:00:00+00:00", "html_ok": "true", "pdf_ok": "true"}
        self.assertIs(better_row(a, b), b)

    def test_merge_rows_dedupes_by_doi(self) -> None:
        base = [{"doi": "10.1/a", "final_status": "failed", "updated_at": "2026-03-29T00:00:00+00:00"}]
        extra = [{"doi": "10.1/A", "final_status": "success", "updated_at": "2026-03-29T00:01:00+00:00"}]
        merged, replaced = merge_rows(base, extra)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged["10.1/a"]["final_status"], "success")
        self.assertEqual(replaced, 1)


if __name__ == "__main__":
    unittest.main()
