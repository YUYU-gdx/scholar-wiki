from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from kn_graph.services.pipeline_runtime import _delete_paper_bundle_by_id, _ensure_parse_artifacts_for_import
from kn_graph.services.sqlite_repo import SqliteRepo


class TestPipelineRuntimePlaceholderCleanup(unittest.TestCase):
    def test_ensure_parse_artifacts_rebuilds_from_mineru_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / "run"
            parse_dir = run_dir / "parse"
            parse_dir.mkdir(parents=True)
            zip_path = parse_dir / "mineru.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("paper/full.md", "# Recovered\n\nBody.")

            meta = {
                "markdown_path": str(parse_dir / "missing.md"),
                "html_path": str(parse_dir / "missing.html"),
                "zip_path": str(zip_path),
            }

            out = _ensure_parse_artifacts_for_import(meta, run_dir, root / "input.pdf")

            self.assertTrue(Path(str(out["markdown_path"])).exists())
            self.assertTrue(Path(str(out["html_path"])).exists())
            self.assertTrue((parse_dir / "mineru_zip_unpacked" / "paper" / "full.md").exists())

    def test_ensure_parse_artifacts_reports_missing_path_when_zip_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / "run"
            parse_dir = run_dir / "parse"
            parse_dir.mkdir(parents=True)
            meta = {
                "markdown_path": str(parse_dir / "missing.md"),
                "html_path": str(parse_dir / "missing.html"),
                "zip_path": str(parse_dir / "missing.zip"),
            }

            with self.assertRaisesRegex(RuntimeError, "parse_artifact_missing:markdown_path:"):
                _ensure_parse_artifacts_for_import(meta, run_dir, root / "input.pdf")

    def test_delete_placeholder_paper_bundle_keeps_canonical_paper(self) -> None:
        conn = sqlite3.connect(":memory:")
        repo = SqliteRepo(conn)
        repo.apply_schema()

        repo.replace_paper_bundle(
            "job::job_123",
            {
                "doi": "job::job_123",
                "title": "placeholder",
                "direct_effects": [
                    {
                        "source": "X",
                        "target": "Y",
                        "effect_form": "positive",
                        "verification": "supported",
                        "evidence_text": "e1",
                    }
                ],
            },
        )
        repo.replace_paper_bundle(
            "paper_key_abc",
            {
                "doi": "10.1234/abc",
                "title": "canonical",
                "direct_effects": [
                    {
                        "source": "A",
                        "target": "B",
                        "effect_form": "positive",
                        "verification": "supported",
                        "evidence_text": "e2",
                    }
                ],
            },
        )

        _delete_paper_bundle_by_id(conn, "job::job_123")
        conn.commit()

        cur = conn.cursor()
        cur.execute("SELECT paper_id FROM papers ORDER BY paper_id")
        paper_ids = [row[0] for row in cur.fetchall()]
        self.assertEqual(paper_ids, ["paper_key_abc"])

        cur.execute("SELECT DISTINCT paper_id FROM direct_effects ORDER BY paper_id")
        effect_paper_ids = [row[0] for row in cur.fetchall()]
        self.assertEqual(effect_paper_ids, ["paper_key_abc"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
