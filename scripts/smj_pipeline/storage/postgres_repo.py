from __future__ import annotations

import json
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
                    paper_id, doi, offline_html_path, article_url, publication_date, online_date,
                    publication_year, paper_citation_count, metadata_source,
                    extractability_status, paper_type, extractability_reason, extractability_evidence_section
                ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(paper_id) DO UPDATE SET
                    doi=excluded.doi,
                    offline_html_path=excluded.offline_html_path,
                    article_url=excluded.article_url,
                    publication_date=excluded.publication_date,
                    online_date=excluded.online_date,
                    publication_year=excluded.publication_year,
                    paper_citation_count=excluded.paper_citation_count,
                    metadata_source=excluded.metadata_source,
                    extractability_status=excluded.extractability_status,
                    paper_type=excluded.paper_type,
                    extractability_reason=excluded.extractability_reason,
                    extractability_evidence_section=excluded.extractability_evidence_section
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
                    str(bundle.get("extractability_status", "") or ""),
                    str(bundle.get("paper_type", "") or ""),
                    str(bundle.get("extractability_reason", "") or ""),
                    str(bundle.get("extractability_evidence_section", "") or ""),
                ),
            )

            self._execute("DELETE FROM paper_domains WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM variable_aliases WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM variable_definitions WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM direct_effects WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM moderations WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM interactions WHERE paper_id = {p}", (paper_id,))

            self._execute(
                "DELETE FROM interaction_inputs WHERE interaction_id NOT IN (SELECT id FROM interactions)",
                (),
            )

            for domain in bundle.get("paper_domains", []) or []:
                domain_text = str(domain or "").strip()
                if not domain_text:
                    continue
                self._execute(
                    "INSERT INTO paper_domains (paper_id, domain, source) VALUES ({p}, {p}, {p})",
                    (paper_id, domain_text, "metadata_or_model"),
                )

            for row in bundle.get("variable_definitions", []) or []:
                variable_name = str(row.get("variable_name", "") or row.get("variable", "") or "").strip()
                aliases = _coerce_aliases(row.get("aliases"), variable_name)
                self._execute(
                    """
                    INSERT INTO variable_definitions (
                        paper_id, variable_name, aliases_json, definition_text, measurement_text
                    ) VALUES ({p}, {p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        variable_name,
                        json.dumps(aliases, ensure_ascii=False),
                        str(row.get("definition", "") or ""),
                        str(row.get("measurement", "") or ""),
                    ),
                )

            for row in bundle.get("direct_effects", []) or []:
                source_var = str(row.get("source", "") or "").strip()
                target_var = str(row.get("target", "") or "").strip()
                source_canonical = _canonical_var_id(source_var)
                target_canonical = _canonical_var_id(target_var)
                source_aliases = _coerce_aliases(row.get("source_aliases"), source_var)
                target_aliases = _coerce_aliases(row.get("target_aliases"), target_var)
                effect_form = str(row.get("effect_form", "") or "").strip().lower()

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

                for alias in source_aliases:
                    self._insert_alias(source_canonical, alias, paper_id)
                for alias in target_aliases:
                    self._insert_alias(target_canonical, alias, paper_id)

                self._execute(
                    """
                    INSERT INTO direct_effects (
                        paper_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id,
                        source_alias_json, target_alias_json, effect_form, theory_name,
                        verification, evidence_text
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        source_var,
                        target_var,
                        source_canonical,
                        target_canonical,
                        json.dumps(source_aliases, ensure_ascii=False),
                        json.dumps(target_aliases, ensure_ascii=False),
                        effect_form,
                        str(row.get("theory_name", "") or ""),
                        str(row.get("verification", "") or ""),
                        str(row.get("evidence_text", "") or ""),
                    ),
                )

            for row in bundle.get("moderations", []) or []:
                moderator_var = str(row.get("moderator", "") or "").strip()
                source_var = str(row.get("source", "") or "").strip()
                target_var = str(row.get("target", "") or "").strip()
                moderator_canonical = _canonical_var_id(moderator_var)
                source_canonical = _canonical_var_id(source_var)
                target_canonical = _canonical_var_id(target_var)
                moderator_aliases = _coerce_aliases(row.get("moderator_aliases"), moderator_var)

                self._execute(
                    """
                    INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                    VALUES ({p}, {p})
                    ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                    """,
                    (moderator_canonical, moderator_var),
                )
                for alias in moderator_aliases:
                    self._insert_alias(moderator_canonical, alias, paper_id)

                if source_var:
                    self._execute(
                        """
                        INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                        VALUES ({p}, {p})
                        ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                        """,
                        (source_canonical, source_var),
                    )
                if target_var:
                    self._execute(
                        """
                        INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                        VALUES ({p}, {p})
                        ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                        """,
                        (target_canonical, target_var),
                    )

                self._execute(
                    """
                    INSERT INTO moderations (
                        paper_id, moderator_var, moderator_canonical_var_id, moderator_alias_json,
                        source_var, target_var, source_canonical_var_id, target_canonical_var_id,
                        effect_form, theory_name, verification, evidence_text
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        moderator_var,
                        moderator_canonical,
                        json.dumps(moderator_aliases, ensure_ascii=False),
                        source_var,
                        target_var,
                        source_canonical,
                        target_canonical,
                        str(row.get("effect_form", "") or ""),
                        str(row.get("theory_name", "") or ""),
                        str(row.get("verification", "") or ""),
                        str(row.get("evidence_text", "") or ""),
                    ),
                )

            for row in bundle.get("interactions", []) or []:
                output_var = str(row.get("output", "") or "").strip()
                output_canonical = _canonical_var_id(output_var)

                if output_var:
                    self._execute(
                        """
                        INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                        VALUES ({p}, {p})
                        ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                        """,
                        (output_canonical, output_var),
                    )

                cursor = self._execute(
                    """
                    INSERT INTO interactions (
                        paper_id, output_var, output_canonical_var_id, effect_form, theory_name,
                        verification, evidence_text
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                    RETURNING id
                    """,
                    (
                        paper_id,
                        output_var,
                        output_canonical,
                        str(row.get("effect_form", "") or ""),
                        str(row.get("theory_name", "") or ""),
                        str(row.get("verification", "") or ""),
                        str(row.get("evidence_text", "") or ""),
                    ),
                )
                fetched = cursor.fetchone()
                interaction_id = int(fetched[0]) if fetched else 0

                inputs = row.get("inputs", []) or []
                for idx, raw_input in enumerate(inputs):
                    input_var = str(raw_input or "")
                    if not input_var:
                        continue
                    input_canonical = _canonical_var_id(input_var)
                    self._execute(
                        """
                        INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                        VALUES ({p}, {p})
                        ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                        """,
                        (input_canonical, input_var),
                    )
                    self._execute(
                        """
                        INSERT INTO interaction_inputs (
                            interaction_id, input_var, input_canonical_var_id, input_order
                        ) VALUES ({p}, {p}, {p}, {p})
                        """,
                        (interaction_id, input_var, input_canonical, idx),
                    )

    def _insert_alias(self, canonical_var_id: str, alias: str, paper_id: str) -> None:
        alias_norm = _normalize_alias(alias)
        self._execute(
            """
            INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
            VALUES ({p}, {p}, {p}, {p}, {p})
            ON CONFLICT(canonical_var_id, alias_norm) DO NOTHING
            """,
            (canonical_var_id, alias, alias_norm, "model", paper_id),
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


def _canonical_var_id(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    return f"var::{value}" if value else "var::unknown"


def _coerce_aliases(value: object, fallback: str) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str) and value.strip():
        raw = [value]
    else:
        raw = []
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
    return out


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
