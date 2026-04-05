from __future__ import annotations

from pathlib import Path
import re
from typing import Any


class PostgresRepo:
    """Source-of-truth repo backed by PostgreSQL (with sqlite fallback for tests)."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        mod = type(connection).__module__.lower()
        self._dialect = "sqlite" if "sqlite3" in mod else "postgres"

    def apply_schema(self) -> None:
        schema_file = "schema_postgres.sql" if self._dialect == "postgres" else "schema.sql"
        schema_path = Path(__file__).with_name(schema_file)
        schema_sql = schema_path.read_text(encoding="utf-8")
        if self._dialect == "sqlite":
            self.connection.executescript(schema_sql)
        else:
            with self.connection:
                with self.connection.cursor() as cur:
                    for statement in schema_sql.split(";"):
                        stmt = statement.strip()
                        if stmt:
                            cur.execute(stmt)
        self.connection.commit()

    def replace_paper_bundle(self, paper_id: str, bundle: dict[str, object]) -> None:
        paper_doi = str(bundle.get("doi", "") or paper_id).strip()
        offline_html_path = str(bundle.get("offline_html_path", "") or "").strip()
        article_url = str(bundle.get("article_url", "") or "").strip()
        publication_date = str(bundle.get("publication_date", "") or "").strip()
        online_date = str(bundle.get("online_date", "") or "").strip()
        publication_year = _to_int(bundle.get("publication_year"))
        paper_citation_count = _to_int(bundle.get("paper_citation_count"))
        metadata_source = str(bundle.get("metadata_source", "") or "manifest_or_model").strip()

        with self.connection:
            self._execute(
                """
                INSERT INTO papers (
                    paper_id, doi, offline_html_path, article_url, publication_date, online_date, publication_year, paper_citation_count, metadata_source
                ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(paper_id) DO UPDATE SET
                    doi=excluded.doi,
                    offline_html_path=excluded.offline_html_path,
                    article_url=excluded.article_url,
                    publication_date=excluded.publication_date,
                    online_date=excluded.online_date,
                    publication_year=excluded.publication_year,
                    paper_citation_count=excluded.paper_citation_count,
                    metadata_source=excluded.metadata_source
                """,
                (
                    paper_id,
                    paper_doi,
                    offline_html_path,
                    article_url,
                    publication_date,
                    online_date,
                    publication_year,
                    paper_citation_count,
                    metadata_source,
                ),
            )
            self._execute("DELETE FROM paper_domains WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM variable_aliases WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM alias_mentions WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM relations WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM variable_theory_grounding WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM relation_theory_grounding WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM hypotheses WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM citations WHERE paper_id = {p}", (paper_id,))

            for domain in bundle.get("paper_domains", []) or []:
                domain_text = str(domain or "").strip()
                if not domain_text:
                    continue
                self._execute(
                    "INSERT INTO paper_domains (paper_id, domain, source) VALUES ({p}, {p}, {p})",
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
                relation_type_raw = str(row.get("relation_type_raw", "") or row.get("relation_type", "") or "").strip()
                relation_type_std = str(row.get("relation_type_std", "") or relation_type_raw or "").strip() or "unspecified"
                moderated = row.get("moderated_relation") if isinstance(row.get("moderated_relation"), dict) else {}

                self._execute(
                    """
                    INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                    VALUES ({p}, {p})
                    ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                    """,
                    (source_canonical, source_var),
                )
                self._execute(
                    """
                    INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                    VALUES ({p}, {p})
                    ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                    """,
                    (target_canonical, target_var),
                )

                cursor = self._execute(
                    """
                    INSERT INTO relations (
                        paper_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id,
                        source_alias_text, target_alias_text, unresolved_abbr, abbr_form, name_resolution_source,
                        relation_type, relation_type_raw, relation_type_std,
                        model_tag, relation_form, direction, verification, evidence_anchor,
                        moderator_var, mediator_var, condition_text, moderated_source_var, moderated_target_var, moderated_hypothesis_label
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    RETURNING id
                    """,
                    (
                        paper_id,
                        source_var,
                        target_var,
                        source_canonical,
                        target_canonical,
                        source_aliases[0] if source_aliases else source_var,
                        target_aliases[0] if target_aliases else target_var,
                        bool(row.get("unresolved_abbr", False)),
                        row.get("abbr_form", ""),
                        row.get("name_resolution_source", ""),
                        relation_type_std,
                        relation_type_raw,
                        relation_type_std,
                        row.get("model_tag", ""),
                        relation_form,
                        row.get("direction", ""),
                        row.get("verification", ""),
                        row.get("evidence_anchor", ""),
                        row.get("moderator_var", ""),
                        row.get("mediator_var", ""),
                        row.get("condition_text", ""),
                        (moderated or {}).get("source_var", ""),
                        (moderated or {}).get("target_var", ""),
                        (moderated or {}).get("hypothesis_label", ""),
                    ),
                )
                fetched = cursor.fetchone()
                relation_row_id = int(fetched[0]) if fetched else 0

                for alias in source_aliases:
                    alias_norm = _normalize_alias(alias)
                    self._execute(
                        """
                        INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
                        VALUES ({p}, {p}, {p}, {p}, {p})
                        ON CONFLICT(canonical_var_id, alias_norm) DO NOTHING
                        """,
                        (source_canonical, alias, alias_norm, "model", paper_id),
                    )
                    self._execute(
                        """
                        INSERT INTO alias_mentions (paper_id, relation_row_id, canonical_var_id, alias_text, alias_norm, role)
                        VALUES ({p}, {p}, {p}, {p}, {p}, 'source')
                        """,
                        (paper_id, relation_row_id, source_canonical, alias, alias_norm),
                    )

                for alias in target_aliases:
                    alias_norm = _normalize_alias(alias)
                    self._execute(
                        """
                        INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
                        VALUES ({p}, {p}, {p}, {p}, {p})
                        ON CONFLICT(canonical_var_id, alias_norm) DO NOTHING
                        """,
                        (target_canonical, alias, alias_norm, "model", paper_id),
                    )
                    self._execute(
                        """
                        INSERT INTO alias_mentions (paper_id, relation_row_id, canonical_var_id, alias_text, alias_norm, role)
                        VALUES ({p}, {p}, {p}, {p}, {p}, 'target')
                        """,
                        (paper_id, relation_row_id, target_canonical, alias, alias_norm),
                    )

            for row in bundle.get("variable_level_theory_grounding", []):
                self._execute(
                    """
                    INSERT INTO variable_theory_grounding (
                        paper_id, variable_name, theory, evidence_anchor
                    ) VALUES ({p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        row.get("variable", ""),
                        row.get("theory", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )

            for row in bundle.get("relation_level_theory_grounding", []):
                self._execute(
                    """
                    INSERT INTO relation_theory_grounding (
                        paper_id, source_var, target_var, theory, evidence_anchor
                    ) VALUES ({p}, {p}, {p}, {p}, {p})
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
                self._execute(
                    """
                    INSERT INTO hypotheses (
                        paper_id, label, statement, verification, evidence_anchor
                    ) VALUES ({p}, {p}, {p}, {p}, {p})
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
                self._execute(
                    """
                    INSERT INTO citations (
                        paper_id, citation_key, source_text, evidence_anchor
                    ) VALUES ({p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        row.get("citation_key", ""),
                        row.get("source_text", ""),
                        row.get("evidence_anchor", ""),
                    ),
                )

    def _execute(self, sql: str, params: tuple[object, ...] = ()) -> Any:
        q = sql.replace("{p}", "?") if self._dialect == "sqlite" else sql.replace("{p}", "%s")
        return self.connection.execute(q, params)


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


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
