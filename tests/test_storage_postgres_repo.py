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


def _bundle(target: str = "B") -> dict[str, object]:
    return {
        "doi": "10.1002/test",
        "publication_date": "2021-03-01",
        "online_date": "2021-01-15",
        "publication_year": 2021,
        "paper_citation_count": 77,
        "extractability_status": "yes",
        "paper_type": "quantitative_empirical",
        "extractability_reason": "has regression",
        "extractability_evidence_section": "Methods",
        "paper_domains": ["strategy"],
        "variable_definitions": [
            {
                "variable_name": "A",
                "aliases": ["alpha"],
                "definition": "A definition",
                "measurement": "survey scale",
            }
        ],
        "direct_effects": [
            {
                "source": "A",
                "target": target,
                "source_aliases": ["A"],
                "target_aliases": [target],
                "effect_form": "positive",
                "theory_name": "RBV",
                "verification": "supported",
                "evidence_text": "H1: coef > 0",
            }
        ],
        "moderations": [
            {
                "moderator": "M",
                "moderator_aliases": ["M"],
                "source": "A",
                "target": target,
                "effect_form": "positive",
                "theory_name": "contingency theory",
                "verification": "supported",
                "evidence_text": "H2: interaction > 0",
            }
        ],
        "interactions": [],
    }


class PostgresRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.repo = PostgresRepo(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_apply_schema_and_replace_paper_bundle_persists_rows(self) -> None:
        self.repo.apply_schema()
        self.repo.replace_paper_bundle("paper-1", _bundle())

        paper = self.connection.execute(
            "SELECT extractability_status, paper_type, publication_year FROM papers WHERE paper_id = ?",
            ("paper-1",),
        ).fetchone()
        direct_effects = self.connection.execute(
            "SELECT source_var, target_var, effect_form, verification, evidence_text FROM direct_effects"
        ).fetchall()
        moderations = self.connection.execute(
            "SELECT moderator_var, source_var, target_var, effect_form FROM moderations"
        ).fetchall()
        variable_defs = self.connection.execute(
            "SELECT variable_name, definition_text, measurement_text FROM variable_definitions"
        ).fetchall()

        self.assertEqual(dict(paper), {"extractability_status": "yes", "paper_type": "quantitative_empirical", "publication_year": 2021})
        self.assertEqual([dict(r) for r in direct_effects], [{"source_var": "A", "target_var": "B", "effect_form": "positive", "verification": "supported", "evidence_text": "H1: coef > 0"}])
        self.assertEqual([dict(r) for r in moderations], [{"moderator_var": "M", "source_var": "A", "target_var": "B", "effect_form": "positive"}])
        self.assertEqual([dict(r) for r in variable_defs], [{"variable_name": "A", "definition_text": "A definition", "measurement_text": "survey scale"}])

    def test_replace_paper_bundle_overwrites_previous_rows(self) -> None:
        self.repo.apply_schema()
        self.repo.replace_paper_bundle("paper-1", _bundle("B"))
        self.repo.replace_paper_bundle("paper-1", _bundle("C"))

        direct_effects = self.connection.execute(
            "SELECT target_var FROM direct_effects WHERE paper_id = ?",
            ("paper-1",),
        ).fetchall()
        self.assertEqual([r[0] for r in direct_effects], ["C"])


if __name__ == "__main__":
    unittest.main()
