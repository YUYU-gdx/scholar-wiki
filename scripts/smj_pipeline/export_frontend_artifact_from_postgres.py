from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export graph artifact from PostgreSQL tables.")
    p.add_argument("--dsn", required=True)
    p.add_argument("--output-json", type=Path, required=True)
    return p.parse_args()


def _slug(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", t).strip("-")
    return t or "unknown"


def _canonical_var_id(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    return f"var::{value}" if value else "var::unknown"


def _fetch_all(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(dict(zip(cols, row)))
        return out


def _loads_json_list(raw: object) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
    except Exception:
        pass
    return []


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _display_effect_class(direction: str, relation_form: str) -> str:
    form = str(relation_form or "").strip().lower()
    if form == "nonlinear":
        return "nonlinear"
    d = str(direction or "").strip().lower()
    if d == "negative":
        return "negative"
    if d == "positive":
        return "positive"
    return "nonlinear"


def _effect_symbol_from_direction(direction: str, relation_form: str) -> str:
    form = str(relation_form or "").strip().lower()
    d = str(direction or "").strip().lower()
    if form == "nonlinear" or d == "nonlinear":
        return "nonlinear"
    if d == "positive":
        return "+"
    if d == "negative":
        return "-"
    if d in {"mixed", "unclear"}:
        return d
    return ""


def _ensure_node(
    variable_nodes: dict[str, dict[str, Any]],
    node_aliases: dict[str, set[str]],
    node_id: str,
    label: str,
    aliases: list[str] | None = None,
) -> None:
    n = variable_nodes.setdefault(node_id, {"id": node_id, "type": "variable", "label": label, "name": label, "canonical_var_id": node_id})
    if label and not str(n.get("label", "")).strip():
        n["label"] = label
    node_aliases.setdefault(node_id, set())
    for v in aliases or []:
        txt = str(v or "").strip()
        if txt:
            node_aliases[node_id].add(txt)


def _fill_node_first_year(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    years_by_node: dict[str, list[int]] = {}
    for edge in edges:
        year = _coerce_optional_int(edge.get("paper_year"))
        if year is None:
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source:
            years_by_node.setdefault(source, []).append(year)
        if target:
            years_by_node.setdefault(target, []).append(year)
    for node_id, node in nodes.items():
        years = years_by_node.get(node_id, [])
        if years:
            node["first_year"] = min(years)


def main() -> None:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Run: uv add psycopg[binary]")

    args = parse_args()
    with psycopg.connect(args.dsn) as conn:
        papers_rows = _fetch_all(
            conn,
            """
            SELECT
              paper_id, doi, title, authors_json, abstract, journal,
              offline_html_path, source_pdf_path, source_md_path, source_html_path,
              article_url, publication_date, online_date,
              publication_year, paper_citation_count,
              extractability_status, paper_type, extractability_reason, extractability_evidence_section,
              created_at, updated_at
            FROM papers
            ORDER BY paper_id
            """,
        )
        domain_rows = _fetch_all(conn, "SELECT paper_id, domain FROM paper_domains ORDER BY paper_id, domain")
        context_rows = _fetch_all(conn, "SELECT paper_id, variable_name FROM context_variables ORDER BY paper_id, id")
        operationalization_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, variable_name, operationalized_as_json
            FROM operationalizations
            ORDER BY paper_id, id
            """,
        )
        def_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, variable_name, aliases_json, definition_text, evidence_section
            FROM variable_definitions
            ORDER BY paper_id, id
            """,
        )
        effect_rows = _fetch_all(
            conn,
            """
            SELECT
              paper_id, source_var, target_var,
              source_canonical_var_id, target_canonical_var_id,
              source_alias_json, target_alias_json,
              direction, relation_form, relation_form_raw, hypothesis_label,
              verification, evidence_section, evidence_snippet
            FROM direct_effects
            ORDER BY paper_id, id
            """,
        )
        mod_rows = _fetch_all(
            conn,
            """
            SELECT
              m.id, m.paper_id, m.moderator_var, m.moderator_canonical_var_id, m.moderator_alias_json,
              m.direction, m.hypothesis_label, m.verification, m.evidence_section, m.evidence_snippet,
              t.source_var, t.target_var, t.source_canonical_var_id, t.target_canonical_var_id
            FROM moderations m
            LEFT JOIN moderation_targets t ON t.moderation_id = m.id
            ORDER BY m.paper_id, m.id, t.id
            """,
        )
        interaction_rows = _fetch_all(
            conn,
            """
            SELECT
              i.id, i.paper_id, i.output_var, i.output_canonical_var_id,
              i.interaction_type, i.moderator_var, i.moderator_canonical_var_id,
              i.effect, i.hypothesis_label, i.verification, i.evidence_section,
              i.evidence_snippet, i.description,
              inp.input_var, inp.input_canonical_var_id, inp.input_order
            FROM interactions i
            LEFT JOIN interaction_inputs inp ON inp.interaction_id = i.id
            ORDER BY i.paper_id, i.id, inp.input_order
            """,
        )
    variable_nodes: dict[str, dict[str, Any]] = {}
    node_aliases: dict[str, set[str]] = {}
    edges: list[dict[str, Any]] = []
    moderation_links: list[dict[str, Any]] = []
    interaction_links: list[dict[str, Any]] = []
    papers_map: dict[str, dict[str, Any]] = {}
    edge_key_seen: set[str] = set()

    for p in papers_rows:
        pid = str(p.get("paper_id", "")).strip()
        if not pid:
            continue
        papers_map[pid] = {
            "paper_id": pid,
            "doi": str(p.get("doi", "") or pid),
            "title": str(p.get("title", "") or ""),
            "authors_json": p.get("authors_json") if isinstance(p.get("authors_json"), list) else [],
            "abstract": str(p.get("abstract", "") or ""),
            "journal": str(p.get("journal", "") or ""),
            "offline_html_path": str(p.get("offline_html_path", "") or ""),
            "source_pdf_path": str(p.get("source_pdf_path", "") or ""),
            "source_md_path": str(p.get("source_md_path", "") or ""),
            "source_html_path": str(p.get("source_html_path", "") or ""),
            "article_url": str(p.get("article_url", "") or ""),
            "publication_date": str(p.get("publication_date", "") or ""),
            "online_date": str(p.get("online_date", "") or ""),
            "publication_year": p.get("publication_year"),
            "paper_citation_count": p.get("paper_citation_count"),
            "extractability_status": str(p.get("extractability_status", "") or ""),
            "paper_type": str(p.get("paper_type", "") or ""),
            "extractability_reason": str(p.get("extractability_reason", "") or ""),
            "extractability_evidence_section": str(p.get("extractability_evidence_section", "") or ""),
            "paper_domains": [],
            "context_variables": [],
            "operationalization": {},
            "variable_definitions": [],
            "main_effects": [],
            "moderations": [],
            "interactions": [],
        }

    for d in domain_rows:
        pid = str(d.get("paper_id", "")).strip()
        if pid in papers_map:
            papers_map[pid]["paper_domains"].append(str(d.get("domain", "") or ""))

    for row in context_rows:
        pid = str(row.get("paper_id", "")).strip()
        if pid not in papers_map:
            continue
        txt = str(row.get("variable_name", "") or "").strip()
        if txt:
            papers_map[pid]["context_variables"].append(txt)

    for row in operationalization_rows:
        pid = str(row.get("paper_id", "")).strip()
        if pid not in papers_map:
            continue
        name = str(row.get("variable_name", "") or "").strip()
        if not name:
            continue
        papers_map[pid]["operationalization"][name] = {
            "operationalized_as": _loads_json_list(row.get("operationalized_as_json"))
        }

    for row in def_rows:
        pid = str(row.get("paper_id", "")).strip()
        if pid not in papers_map:
            continue
        papers_map[pid]["variable_definitions"].append(
            {
                "variable": str(row.get("variable_name", "") or ""),
                "aliases": _loads_json_list(row.get("aliases_json")),
                "definition": str(row.get("definition_text", "") or ""),
                "definition_evidence_section": str(row.get("evidence_section", "") or ""),
            }
        )

    for rel in effect_rows:
        pid = str(rel.get("paper_id", "")).strip()
        source = str(rel.get("source_var", "")).strip()
        target = str(rel.get("target_var", "")).strip()
        if pid not in papers_map or not source or not target:
            continue
        source_id = _canonical_var_id(source)
        target_id = _canonical_var_id(target)
        source_aliases = _loads_json_list(rel.get("source_alias_json"))
        target_aliases = _loads_json_list(rel.get("target_alias_json"))
        _ensure_node(variable_nodes, node_aliases, source_id, source, source_aliases)
        _ensure_node(variable_nodes, node_aliases, target_id, target, target_aliases)

        rel_payload = {
            "source": source,
            "target": target,
            "source_aliases": source_aliases,
            "target_aliases": target_aliases,
            "source_canonical_var_id": source_id,
            "target_canonical_var_id": target_id,
            "direction": str(rel.get("direction", "") or ""),
            "relation_form": str(rel.get("relation_form", "") or ""),
            "relation_form_raw": str(rel.get("relation_form_raw", "") or ""),
            "hypothesis_label": str(rel.get("hypothesis_label", "") or ""),
            "verification": str(rel.get("verification", "") or ""),
            "evidence_section": str(rel.get("evidence_section", "") or ""),
            "evidence_snippet": str(rel.get("evidence_snippet", "") or ""),
        }
        papers_map[pid]["main_effects"].append(
            {
                "from": source,
                "to": target,
                "effect": _effect_symbol_from_direction(rel_payload["direction"], rel_payload["relation_form"]),
                "hypothesis_label": rel_payload["hypothesis_label"],
                "verification": rel_payload["verification"],
                "evidence_section": rel_payload["evidence_section"],
                "evidence_snippet": rel_payload["evidence_snippet"],
                "description": "",
            }
        )

        rel_std = "main_effect"
        dedupe_key = f"{pid}|{source_id}|{target_id}|{rel_std}|{rel_payload['evidence_section']}"
        if dedupe_key in edge_key_seen:
            continue
        edge_key_seen.add(dedupe_key)
        edges.append(
            {
                "id": f"edge::{_slug(pid)}::{_slug(source)}::{_slug(target)}::{len(edges)}",
                "source": source_id,
                "target": target_id,
                "source_name_local": source,
                "target_name_local": target,
                "paper_id": pid,
                "doi": str(papers_map[pid].get("doi", "") or pid),
                "relation_type": "main_effect",
                "relation_type_std": rel_std,
                "direction": rel_payload["direction"],
                "relation_form": rel_payload["relation_form"],
                "verification": rel_payload["verification"],
                "evidence_section": rel_payload["evidence_section"],
                "evidence_snippet": rel_payload["evidence_snippet"],
                "hypothesis_label": rel_payload["hypothesis_label"],
                "paper_year": papers_map[pid].get("publication_year"),
                "display_effect_class": _display_effect_class(rel_payload["direction"], rel_payload["relation_form"]),
            }
        )

    moderation_group: dict[tuple[str, int], dict[str, Any]] = {}
    for row in mod_rows:
        pid = str(row.get("paper_id", "")).strip()
        mid = int(row.get("id") or 0)
        if pid not in papers_map or mid <= 0:
            continue
        key = (pid, mid)
        if key not in moderation_group:
            moderator = str(row.get("moderator_var", "") or "")
            mod_node = _canonical_var_id(moderator)
            _ensure_node(variable_nodes, node_aliases, mod_node, moderator, _loads_json_list(row.get("moderator_alias_json")))
            moderation_group[key] = {
                "moderator": moderator,
                "moderator_aliases": _loads_json_list(row.get("moderator_alias_json")),
                "moderator_node_id": mod_node,
                "direction": str(row.get("direction", "") or ""),
                "hypothesis_label": str(row.get("hypothesis_label", "") or ""),
                "verification": str(row.get("verification", "") or ""),
                "evidence_section": str(row.get("evidence_section", "") or ""),
                "evidence_snippet": str(row.get("evidence_snippet", "") or ""),
                "targets": [],
            }

        src = str(row.get("source_var", "") or "").strip()
        tgt = str(row.get("target_var", "") or "").strip()
        if src and tgt:
            src_node_id = _canonical_var_id(src)
            tgt_node_id = _canonical_var_id(tgt)
            _ensure_node(variable_nodes, node_aliases, src_node_id, src, [])
            _ensure_node(variable_nodes, node_aliases, tgt_node_id, tgt, [])
            moderation_group[key]["targets"].append(
                {
                    "source": src,
                    "target": tgt,
                    "source_node_id": src_node_id,
                    "target_node_id": tgt_node_id,
                }
            )

    for (pid, _mid), item in moderation_group.items():
        mod_payload = {
            "moderator": item["moderator"],
            "moderator_aliases": item["moderator_aliases"],
            "moderated_effects": [{"source": t["source"], "target": t["target"]} for t in item["targets"]],
            "direction": item["direction"],
            "hypothesis_label": item["hypothesis_label"],
            "verification": item["verification"],
            "evidence_section": item["evidence_section"],
            "evidence_snippet": item["evidence_snippet"],
            "condition_text": "",
        }
        papers_map[pid]["moderations"].append(mod_payload)

        for t in item["targets"]:
            moderation_links.append(
                {
                    "id": f"mod::{_slug(pid)}::{_slug(item['moderator'])}::{len(moderation_links)}",
                    "paper_id": pid,
                    "doi": str(papers_map[pid].get("doi", "") or pid),
                    "moderator_var": item["moderator"],
                    "moderator_node_id": item["moderator_node_id"],
                    "moderated_relation": {
                        "source_var": t["source"],
                        "target_var": t["target"],
                        "source_node_id": t["source_node_id"],
                        "target_node_id": t["target_node_id"],
                    },
                    "direction": item["direction"],
                    "verification": item["verification"],
                    "hypothesis_label": item["hypothesis_label"],
                    "condition_text": "",
                    "evidence_section": item["evidence_section"],
                    "evidence_snippet": item["evidence_snippet"],
                    "paper_year": papers_map[pid].get("publication_year"),
                }
            )

    interaction_group: dict[tuple[str, int], dict[str, Any]] = {}
    for row in interaction_rows:
        pid = str(row.get("paper_id", "")).strip()
        iid = int(row.get("id") or 0)
        if pid not in papers_map or iid <= 0:
            continue
        key = (pid, iid)
        if key not in interaction_group:
            output = str(row.get("output_var", "") or "")
            output_id = _canonical_var_id(output)
            _ensure_node(variable_nodes, node_aliases, output_id, output, [])
            moderator = str(row.get("moderator_var", "") or "")
            moderator_id = _canonical_var_id(moderator) if moderator else ""
            if moderator and moderator_id:
                _ensure_node(variable_nodes, node_aliases, moderator_id, moderator, [])

            interaction_group[key] = {
                "paper_id": pid,
                "output": output,
                "output_node_id": output_id,
                "interaction_type": str(row.get("interaction_type", "") or ""),
                "moderator": moderator,
                "moderator_node_id": moderator_id,
                "effect": str(row.get("effect", "") or ""),
                "hypothesis_label": str(row.get("hypothesis_label", "") or ""),
                "verification": str(row.get("verification", "") or ""),
                "evidence_section": str(row.get("evidence_section", "") or ""),
                "evidence_snippet": str(row.get("evidence_snippet", "") or ""),
                "description": str(row.get("description", "") or ""),
                "paper_year": papers_map[pid].get("publication_year"),
                "inputs": [],
                "input_node_ids": [],
            }

        input_var = str(row.get("input_var", "") or "").strip()
        if input_var:
            input_id = _canonical_var_id(input_var)
            _ensure_node(variable_nodes, node_aliases, input_id, input_var, [])
            interaction_group[key]["inputs"].append(input_var)
            interaction_group[key]["input_node_ids"].append(input_id)

    for (pid, _iid), item in interaction_group.items():
        papers_map[pid]["interactions"].append(
            {
                "inputs": list(item["inputs"]),
                "output": item["output"],
                "type": item["interaction_type"],
                "moderator": item["moderator"],
                "effect": item["effect"],
                "hypothesis_label": item["hypothesis_label"],
                "verification": item["verification"],
                "evidence_section": item["evidence_section"],
                "evidence_snippet": item["evidence_snippet"],
                "description": item["description"],
                "input_canonical_var_ids": list(item["input_node_ids"]),
                "output_canonical_var_id": item["output_node_id"],
                "moderator_canonical_var_id": item["moderator_node_id"],
            }
        )
        interaction_links.append(
            {
                "id": f"int::{_slug(pid)}::{len(interaction_links)}",
                "paper_id": pid,
                "doi": str(papers_map[pid].get("doi", "") or pid),
                "inputs": list(item["inputs"]),
                "input_node_ids": list(item["input_node_ids"]),
                "output": item["output"],
                "output_node_id": item["output_node_id"],
                "interaction_type": item["interaction_type"],
                "moderator": item["moderator"],
                "moderator_node_id": item["moderator_node_id"],
                "effect": item["effect"],
                "verification": item["verification"],
                "hypothesis_label": item["hypothesis_label"],
                "evidence_section": item["evidence_section"],
                "evidence_snippet": item["evidence_snippet"],
                "description": item["description"],
                "paper_year": item["paper_year"],
            }
        )
        interaction_type_text = str(item["interaction_type"] or "").strip().lower()
        moderator_node_id = str(item["moderator_node_id"] or "").strip()
        moderator_name = str(item["moderator"] or "").strip()
        output_node_id = str(item["output_node_id"] or "").strip()
        output_name = str(item["output"] or "").strip()
        is_moderation_like = (
            ("moderat" in interaction_type_text)
            or (moderator_node_id != "" and len(item["input_node_ids"]) >= 2)
        )
        if is_moderation_like and moderator_node_id and output_node_id:
            for idx, source_node_id in enumerate(item["input_node_ids"]):
                source_node_id = str(source_node_id or "").strip()
                if not source_node_id or source_node_id == moderator_node_id:
                    continue
                source_name = ""
                if idx < len(item["inputs"]):
                    source_name = str(item["inputs"][idx] or "").strip()
                moderation_links.append(
                    {
                        "id": f"mod::from_inter::{_slug(pid)}::{len(moderation_links)}",
                        "paper_id": pid,
                        "doi": str(papers_map[pid].get("doi", "") or pid),
                        "moderator_var": moderator_name,
                        "moderator_node_id": moderator_node_id,
                        "moderated_relation": {
                            "source_var": source_name,
                            "target_var": output_name,
                            "source_node_id": source_node_id,
                            "target_node_id": output_node_id,
                        },
                        "direction": str(item["effect"] or ""),
                        "verification": str(item["verification"] or ""),
                        "hypothesis_label": str(item["hypothesis_label"] or ""),
                        "condition_text": "",
                        "evidence_section": str(item["evidence_section"] or ""),
                        "evidence_snippet": str(item["evidence_snippet"] or ""),
                        "paper_year": item["paper_year"],
                    }
                )

    _fill_node_first_year(variable_nodes, edges)
    for node_id, aliases in node_aliases.items():
        node = variable_nodes.get(node_id)
        if node is not None:
            node["aliases"] = sorted(aliases)
            node["alias_count"] = len(aliases)

    payload = {
        "meta": {
            "node_count": len(variable_nodes),
            "edge_count": len(edges),
            "paper_count": len(papers_map),
            "interaction_count": len(interaction_links),
        },
        "nodes": list(variable_nodes.values()),
        "edges": edges,
        "moderation_links": moderation_links,
        "interaction_links": interaction_links,
        "papers": list(papers_map.values()),
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
