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
                "variable": "A",
                "aliases": ["alpha"],
                "definition": "A definition",
                "definition_evidence_section": "Theory",
            }
        ],
        "direct_effects": [
            {
                "source": "A",
                "target": target,
                "source_aliases": ["A"],
                "target_aliases": [target],
                "direction": "positive",
                "relation_form": "linear",
                "relation_form_raw": "",
                "hypothesis_label": "H1",
                "verification": "supported",
                "evidence_section": "Results",
                "evidence_snippet": "coef > 0",
            }
        ],
        "moderations": [
            {
                "moderator": "M",
                "moderator_aliases": ["M"],
                "moderated_effects": [{"source": "A", "target": target}],
                "direction": "positive",
                "hypothesis_label": "H2",
                "verification": "supported",
                "evidence_section": "Results",
                "evidence_snippet": "interaction > 0",
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
            "SELECT source_var, target_var, direction, verification FROM direct_effects"
        ).fetchall()
        moderations = self.connection.execute(
            "SELECT moderator_var, direction FROM moderations"
        ).fetchall()
        targets = self.connection.execute(
            "SELECT source_var, target_var FROM moderation_targets"
        ).fetchall()

        self.assertEqual(dict(paper), {"extractability_status": "yes", "paper_type": "quantitative_empirical", "publication_year": 2021})
        self.assertEqual([dict(r) for r in direct_effects], [{"source_var": "A", "target_var": "B", "direction": "positive", "verification": "supported"}])
        self.assertEqual([dict(r) for r in moderations], [{"moderator_var": "M", "direction": "positive"}])
        self.assertEqual([dict(r) for r in targets], [{"source_var": "A", "target_var": "B"}])

    def test_replace_paper_bundle_overwrites_previous_rows(self) -> None:
        self.repo.apply_schema()
        self.repo.replace_paper_bundle("paper-1", _bundle("B"))
        self.repo.replace_paper_bundle("paper-1", _bundle("C"))

        direct_effects = self.connection.execute(
            "SELECT target_var FROM direct_effects WHERE paper_id = ?",
            ("paper-1",),
        ).fetchall()
        self.assertEqual([r[0] for r in direct_effects], ["C"])

    def test_moderation_targets_use_provided_canonical_ids(self) -> None:
        self.repo.apply_schema()
        b = _bundle("B")
        b["moderations"] = [
            {
                "moderator": "M",
                "moderator_aliases": ["M"],
                "moderated_effects": [
                    {
                        "source": "A short",
                        "target": "B short",
                        "source_canonical_var_id": "var::alpha-canonical",
                        "target_canonical_var_id": "var::beta-canonical",
                    }
                ],
                "direction": "positive",
                "hypothesis_label": "H2",
                "verification": "supported",
                "evidence_section": "Results",
                "evidence_snippet": "interaction > 0",
            }
        ]
        self.repo.replace_paper_bundle("paper-1", b)

        targets = self.connection.execute(
            "SELECT source_var, target_var, source_canonical_var_id, target_canonical_var_id FROM moderation_targets"
        ).fetchall()
        self.assertEqual(
            [dict(r) for r in targets],
            [
                {
                    "source_var": "A short",
                    "target_var": "B short",
                    "source_canonical_var_id": "var::alpha-canonical",
                    "target_canonical_var_id": "var::beta-canonical",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()

