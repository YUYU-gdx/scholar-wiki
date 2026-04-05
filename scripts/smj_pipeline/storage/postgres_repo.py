from __future__ import annotations

import sqlite3
from pathlib import Path
import re


class PostgresRepo:
    """SQLite-backed source-of-truth repo for local MVP tests."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def apply_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        self.connection.executescript(schema_sql)
        self.connection.commit()

    def replace_paper_bundle(self, paper_id: str, bundle: dict[str, object]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO papers (paper_id) VALUES (?) "
                "ON CONFLICT(paper_id) DO UPDATE SET paper_id=excluded.paper_id",
                (paper_id,),
            )
            self.connection.execute("DELETE FROM paper_domains WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM variable_aliases WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM alias_mentions WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM relations WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM variable_theory_grounding WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM relation_theory_grounding WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM hypotheses WHERE paper_id = ?", (paper_id,))
            self.connection.execute("DELETE FROM citations WHERE paper_id = ?", (paper_id,))

            for domain in bundle.get("paper_domains", []) or []:
                domain_text = str(domain or "").strip()
                if not domain_text:
                    continue
                self.connection.execute(
                    "INSERT INTO paper_domains (paper_id, domain, source) VALUES (?, ?, ?)",
                    (paper_id, domain_text, "metadata_or_model"),
                )

            for row in bundle.get("relations", []) or []:
                source_var = str(row.get("source_var", "") or "")
                target_var = str(row.get("target_var", "") or "")
                source_canonical = str(row.get("source_canonical_var_id", "") or "").strip() or f"var::{_slug(source_var)}"
                target_canonical = str(row.get("target_canonical_var_id", "") or "").strip() or f"var::{_slug(target_var)}"
                source_aliases = _coerce_aliases(row.get("source_aliases"), source_var)
                target_aliases = _coerce_aliases(row.get("target_aliases"), target_var)
                relation_form = str(row.get("relation_form", "") or "").strip().lower() or "linear"

                self.connection.execute(
                    """
                    INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                    VALUES (?, ?)
                    ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                    """,
                    (source_canonical, source_var),
                )
                self.connection.execute(
                    """
                    INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                    VALUES (?, ?)
                    ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                    """,
                    (target_canonical, target_var),
                )

                cursor = self.connection.execute(
                    """
                    INSERT INTO relations (
                        paper_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id,
                        source_alias_text, target_alias_text, relation_type, model_tag, relation_form,
                        direction, verification, evidence_anchor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        source_var,
                        target_var,
                        source_canonical,
                        target_canonical,
                        source_aliases[0] if source_aliases else source_var,
                        target_aliases[0] if target_aliases else target_var,
                        row.get("relation_type", ""),
                        row.get("model_tag", ""),
                        relation_form,
                        row.get("direction", ""),
                        row.get("verification", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )
                relation_row_id = int(cursor.lastrowid or 0)

                for alias in source_aliases:
                    alias_norm = _normalize_alias(alias)
                    self.connection.execute(
                        """
                        INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(canonical_var_id, alias_norm) DO NOTHING
                        """,
                        (source_canonical, alias, alias_norm, "model", paper_id),
                    )
                    self.connection.execute(
                        """
                        INSERT INTO alias_mentions (paper_id, relation_row_id, canonical_var_id, alias_text, alias_norm, role)
                        VALUES (?, ?, ?, ?, ?, 'source')
                        """,
                        (paper_id, relation_row_id, source_canonical, alias, alias_norm),
                    )

                for alias in target_aliases:
                    alias_norm = _normalize_alias(alias)
                    self.connection.execute(
                        """
                        INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(canonical_var_id, alias_norm) DO NOTHING
                        """,
                        (target_canonical, alias, alias_norm, "model", paper_id),
                    )
                    self.connection.execute(
                        """
                        INSERT INTO alias_mentions (paper_id, relation_row_id, canonical_var_id, alias_text, alias_norm, role)
                        VALUES (?, ?, ?, ?, ?, 'target')
                        """,
                        (paper_id, relation_row_id, target_canonical, alias, alias_norm),
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


def _normalize_alias(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", t).strip("-")
    return t or "unknown"


def _slug(text: str) -> str:
    return _normalize_alias(text)


def _coerce_aliases(value: object, fallback: str) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str) and value.strip():
        raw = [value]
    else:
        raw = [fallback]
    out: list[str] = []
    seen: set[str] = set()
    for v in raw:
        txt = str(v or "").strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out or ([fallback] if fallback else [])
