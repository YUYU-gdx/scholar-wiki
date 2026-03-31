from __future__ import annotations

import sqlite3
from pathlib import Path


class PostgresRepo:
    """SQLite-backed source-of-truth repo for local MVP tests."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def apply_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        self.connection.executescript(schema_sql)
        self.connection.commit()

    def replace_paper_bundle(self, paper_id: str, bundle: dict[str, list[dict[str, str]]]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO papers (paper_id) VALUES (?) "
                "ON CONFLICT(paper_id) DO UPDATE SET paper_id=excluded.paper_id",
                (paper_id,),
            )
            self.connection.execute("DELETE FROM relations WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM variable_theory_grounding WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM relation_theory_grounding WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM hypotheses WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM citations WHERE paper_id = ?", (paper_id,))

            for row in bundle.get("relations", []):
                self.connection.execute(
                    """
                    INSERT INTO relations (
                        paper_id, source_var, target_var, relation_type, model_tag,
                        direction, verification, evidence_anchor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        row.get("source_var", ""),
                        row.get("target_var", ""),
                        row.get("relation_type", ""),
                        row.get("model_tag", ""),
                        row.get("direction", ""),
                        row.get("verification", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )

            for row in bundle.get("variable_level_theory_grounding", []):
                self.connection.execute(
                    """
                    INSERT INTO variable_theory_grounding (
                        paper_id, variable_name, theory, evidence_anchor
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        row.get("variable", ""),
                        row.get("theory", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )

            for row in bundle.get("relation_level_theory_grounding", []):
                self.connection.execute(
                    """
                    INSERT INTO relation_theory_grounding (
                        paper_id, source_var, target_var, theory, evidence_anchor
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        row.get("source_var", ""),
                        row.get("target_var", ""),
                        row.get("theory", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )

            for row in bundle.get("hypotheses", []):
                self.connection.execute(
                    """
                    INSERT INTO hypotheses (
                        paper_id, label, statement, verification, evidence_anchor
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        row.get("label", ""),
                        row.get("statement", ""),
                        row.get("verification", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )

            for row in bundle.get("citations", []):
                self.connection.execute(
                    """
                    INSERT INTO citations (
                        paper_id, citation_key, source_text, evidence_anchor
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        row.get("citation_key", ""),
                        row.get("source_text", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )
