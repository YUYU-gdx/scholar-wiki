from __future__ import annotations

import sqlite3
import unittest

from kn_graph.services.pipeline_runtime import _delete_paper_bundle_by_id
from kn_graph.services.sqlite_repo import SqliteRepo


class TestPipelineRuntimePlaceholderCleanup(unittest.TestCase):
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

