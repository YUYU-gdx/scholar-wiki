from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "storage" / "postgres_repo.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_storage_postgres_repo", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

PostgresRepo = _MOD.PostgresRepo


def _bundle(
    relation_target: str = "B",
    hypothesis_label: str = "H1",
    citation_key: str = "Teece2007",
) -> dict[str, list[dict[str, str]]]:
    return {
        "relations": [
            {
                "source_var": "A",
                "target_var": relation_target,
                "relation_type": "direct",
                "model_tag": "main_model",
                "direction": "positive",
                "verification": "supported",
                "evidence_anchor": "Results paragraph 1",
            }
        ],
        "variable_level_theory_grounding": [
            {
                "variable": "A",
                "theory": "dynamic capabilities",
                "evidence_anchor": "Theory section",
            }
        ],
        "relation_level_theory_grounding": [
            {
                "source_var": "A",
                "target_var": relation_target,
                "theory": "dynamic capabilities",
                "evidence_anchor": "Hypothesis section",
            }
        ],
        "hypotheses": [
            {
                "label": hypothesis_label,
                "statement": f"{hypothesis_label}: A positively affects {relation_target}.",
                "verification": "supported",
                "evidence_anchor": "Results paragraph 1",
            }
        ],
        "citations": [
            {
                "source_text": "Teece (2007)",
                "citation_key": citation_key,
                "evidence_anchor": "Theory section",
            }
        ],
    }


class PostgresRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.repo = PostgresRepo(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_apply_schema_and_replace_paper_bundle_persists_source_of_truth_rows(self) -> None:
        self.repo.apply_schema()

        self.repo.replace_paper_bundle("paper-1", _bundle())

        papers = self.connection.execute("SELECT paper_id FROM papers").fetchall()
        relations = self.connection.execute(
            "SELECT source_var, target_var, relation_type, direction, verification FROM relations"
        ).fetchall()
        variable_grounding = self.connection.execute(
            "SELECT variable_name, theory FROM variable_theory_grounding"
        ).fetchall()
        relation_grounding = self.connection.execute(
            "SELECT source_var, target_var, theory FROM relation_theory_grounding"
        ).fetchall()
        hypotheses = self.connection.execute(
            "SELECT label, verification FROM hypotheses"
        ).fetchall()
        citations = self.connection.execute(
            "SELECT citation_key, source_text FROM citations"
        ).fetchall()

        self.assertEqual([row["paper_id"] for row in papers], ["paper-1"])
        self.assertEqual(
            [dict(row) for row in relations],
            [
                {
                    "source_var": "A",
                    "target_var": "B",
                    "relation_type": "direct",
                    "direction": "positive",
                    "verification": "supported",
                }
            ],
        )
        self.assertEqual([dict(row) for row in variable_grounding], [{"variable_name": "A", "theory": "dynamic capabilities"}])
        self.assertEqual(
            [dict(row) for row in relation_grounding],
            [{"source_var": "A", "target_var": "B", "theory": "dynamic capabilities"}],
        )
        self.assertEqual([dict(row) for row in hypotheses], [{"label": "H1", "verification": "supported"}])
        self.assertEqual([dict(row) for row in citations], [{"citation_key": "Teece2007", "source_text": "Teece (2007)"}])

    def test_replace_paper_bundle_deletes_previous_child_rows_for_same_paper(self) -> None:
        self.repo.apply_schema()
        self.repo.replace_paper_bundle("paper-1", _bundle())

        self.repo.replace_paper_bundle(
            "paper-1",
            _bundle(relation_target="C", hypothesis_label="H2", citation_key="Barney1991"),
        )

        relation_rows = self.connection.execute(
            "SELECT target_var FROM relations WHERE paper_id = ? ORDER BY target_var",
            ("paper-1",),
        ).fetchall()
        hypothesis_rows = self.connection.execute(
            "SELECT label FROM hypotheses WHERE paper_id = ? ORDER BY label",
            ("paper-1",),
        ).fetchall()
        citation_rows = self.connection.execute(
            "SELECT citation_key FROM citations WHERE paper_id = ? ORDER BY citation_key",
            ("paper-1",),
        ).fetchall()

        self.assertEqual([row["target_var"] for row in relation_rows], ["C"])
        self.assertEqual([row["label"] for row in hypothesis_rows], ["H2"])
        self.assertEqual([row["citation_key"] for row in citation_rows], ["Barney1991"])


if __name__ == "__main__":
    unittest.main()
