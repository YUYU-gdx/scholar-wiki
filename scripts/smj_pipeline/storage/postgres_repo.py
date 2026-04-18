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
            self._execute("DELETE FROM context_variables WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM operationalizations WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM direct_effects WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM moderations WHERE paper_id = {p}", (paper_id,))
            self._execute("DELETE FROM interactions WHERE paper_id = {p}", (paper_id,))

            # Remove orphaned relation-input rows from previous replace cycles.
            self._execute(
                "DELETE FROM moderation_targets WHERE moderation_id NOT IN (SELECT id FROM moderations)",
                (),
            )
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
                aliases = _coerce_aliases(row.get("aliases"), str(row.get("variable", "") or ""))
                self._execute(
                    """
                    INSERT INTO variable_definitions (
                        paper_id, variable_name, aliases_json, definition_text, evidence_section
                    ) VALUES ({p}, {p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        str(row.get("variable", "") or ""),
                        json.dumps(aliases, ensure_ascii=False),
                        str(row.get("definition", "") or ""),
                        str(row.get("definition_evidence_section", "") or ""),
                    ),
                )

            for name in bundle.get("context_variables", []) or []:
                variable_name = str(name or "").strip()
                if not variable_name:
                    continue
                self._execute(
                    "INSERT INTO context_variables (paper_id, variable_name) VALUES ({p}, {p})",
                    (paper_id, variable_name),
                )

            operationalization = bundle.get("operationalization", {}) or {}
            if isinstance(operationalization, dict):
                for variable_name, spec in operationalization.items():
                    name = str(variable_name or "").strip()
                    if not name:
                        continue
                    values: list[str] = []
                    if isinstance(spec, dict):
                        values = _coerce_aliases(spec.get("operationalized_as"), "")
                    elif isinstance(spec, list):
                        values = _coerce_aliases(spec, "")
                    elif isinstance(spec, str):
                        values = _coerce_aliases([spec], "")
                    self._execute(
                        """
                        INSERT INTO operationalizations (
                            paper_id, variable_name, operationalized_as_json
                        ) VALUES ({p}, {p}, {p})
                        """,
                        (paper_id, name, json.dumps(values, ensure_ascii=False)),
                    )

            main_effects = bundle.get("main_effects", None)
            if not isinstance(main_effects, list):
                main_effects = []
            direct_effect_rows = bundle.get("direct_effects", None)
            if not isinstance(direct_effect_rows, list):
                direct_effect_rows = []
            source_effect_rows = main_effects if main_effects else direct_effect_rows

            for row in source_effect_rows:
                source_var = str(row.get("source", "") or row.get("from", "") or "")
                target_var = str(row.get("target", "") or row.get("to", "") or "")
                direction = str(row.get("direction", "") or "").strip()
                relation_form = str(row.get("relation_form", "") or "").strip()
                relation_form_raw = str(row.get("relation_form_raw", "") or "").strip()
                if not direction:
                    direction, relation_form, relation_form_raw = _map_main_effect_to_direction(
                        str(row.get("effect", "") or ""),
                        relation_form,
                        relation_form_raw,
                    )
                source_canonical = _canonical_var_id(source_var)
                target_canonical = _canonical_var_id(target_var)
                source_aliases = _coerce_aliases(row.get("source_aliases"), source_var)
                target_aliases = _coerce_aliases(row.get("target_aliases"), target_var)

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
                        source_alias_json, target_alias_json, direction, relation_form, relation_form_raw,
                        hypothesis_label, verification, evidence_section, evidence_snippet
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """,
                    (
                        paper_id,
                        source_var,
                        target_var,
                        source_canonical,
                        target_canonical,
                        json.dumps(source_aliases, ensure_ascii=False),
                        json.dumps(target_aliases, ensure_ascii=False),
                        direction,
                        relation_form,
                        relation_form_raw,
                        str(row.get("hypothesis_label", "") or ""),
                        str(row.get("verification", "") or ""),
                        str(row.get("evidence_section", "") or ""),
                        str(row.get("evidence_snippet", "") or row.get("description", "") or ""),
                    ),
                )

            for row in bundle.get("moderations", []) or []:
                moderator_var = str(row.get("moderator", "") or "")
                moderator_canonical = _canonical_var_id(moderator_var)
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

                cursor = self._execute(
                    """
                    INSERT INTO moderations (
                        paper_id, moderator_var, moderator_canonical_var_id, moderator_alias_json,
                        direction, hypothesis_label, verification, evidence_section, evidence_snippet
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    RETURNING id
                    """,
                    (
                        paper_id,
                        moderator_var,
                        moderator_canonical,
                        json.dumps(moderator_aliases, ensure_ascii=False),
                        str(row.get("direction", "") or ""),
                        str(row.get("hypothesis_label", "") or ""),
                        str(row.get("verification", "") or ""),
                        str(row.get("evidence_section", "") or ""),
                        str(row.get("evidence_snippet", "") or ""),
                    ),
                )
                fetched = cursor.fetchone()
                moderation_id = int(fetched[0]) if fetched else 0

                for item in row.get("moderated_effects", []) or []:
                    src = str(item.get("source", "") or "")
                    tgt = str(item.get("target", "") or "")
                    if not src or not tgt:
                        continue
                    src_id = str(item.get("source_canonical_var_id", "") or "").strip() or _canonical_var_id(src)
                    tgt_id = str(item.get("target_canonical_var_id", "") or "").strip() or _canonical_var_id(tgt)
                    self._execute(
                        """
                        INSERT INTO moderation_targets (
                            moderation_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id
                        ) VALUES ({p}, {p}, {p}, {p}, {p})
                        """,
                        (moderation_id, src, tgt, src_id, tgt_id),
                    )

            for row in bundle.get("interactions", []) or []:
                output_var = str(row.get("output", "") or "")
                output_canonical = _canonical_var_id(output_var)
                moderator_var = str(row.get("moderator", "") or "")
                moderator_canonical = _canonical_var_id(moderator_var)

                if output_var:
                    self._execute(
                        """
                        INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                        VALUES ({p}, {p})
                        ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                        """,
                        (output_canonical, output_var),
                    )

                if moderator_var and moderator_canonical:
                    self._execute(
                        """
                        INSERT INTO canonical_variables (canonical_var_id, canonical_name)
                        VALUES ({p}, {p})
                        ON CONFLICT(canonical_var_id) DO UPDATE SET canonical_name=excluded.canonical_name
                        """,
                        (moderator_canonical, moderator_var),
                    )
                    for alias in _coerce_aliases(row.get("moderator_aliases"), moderator_var):
                        self._insert_alias(moderator_canonical, alias, paper_id)

                cursor = self._execute(
                    """
                    INSERT INTO interactions (
                        paper_id, output_var, output_canonical_var_id, interaction_type,
                        moderator_var, moderator_canonical_var_id, effect, hypothesis_label,
                        verification, evidence_section, evidence_snippet, description
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    RETURNING id
                    """,
                    (
                        paper_id,
                        output_var,
                        output_canonical,
                        str(row.get("type", "") or ""),
                        moderator_var,
                        moderator_canonical,
                        str(row.get("effect", "") or ""),
                        str(row.get("hypothesis_label", "") or ""),
                        str(row.get("verification", "") or ""),
                        str(row.get("evidence_section", "") or ""),
                        str(row.get("evidence_snippet", "") or ""),
                        str(row.get("description", "") or ""),
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


def _map_main_effect_to_direction(effect: str, relation_form: str, relation_form_raw: str) -> tuple[str, str, str]:
    raw = str(effect or "").strip()
    text = raw.lower()
    form = str(relation_form or "").strip().lower() or "linear"
    form_raw = str(relation_form_raw or "").strip()
    if text in {"+", "positive"}:
        return "positive", form, form_raw
    if text in {"-", "negative"}:
        return "negative", form, form_raw
    if text in {"mixed", "unclear"}:
        return text, form, form_raw
    if "nonlinear" in text or "u" in text or "curve" in text:
        return "nonlinear", "nonlinear", raw if raw else form_raw
    if text:
        return "unclear", form, raw if raw else form_raw
    return "unclear", form, form_raw


