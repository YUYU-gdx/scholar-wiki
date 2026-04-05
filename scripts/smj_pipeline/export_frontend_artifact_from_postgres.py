from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export graph artifact from PostgreSQL tables.")
    p.add_argument("--dsn", required=True, help="PostgreSQL DSN, e.g. postgresql://user:pass@host:5432/db")
    p.add_argument("--output-json", type=Path, required=True)
    return p.parse_args()


def _slug(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", t).strip("-")
    return t or "unknown"


def _strength_from_verification(verification: str) -> float:
    m = {
        "supported": 1.0,
        "partially_supported": 0.5,
        "not_supported": 0.0,
    }
    return m.get(str(verification or "").strip(), 0.0)


def _display_effect_class(direction: str, relation_form: str) -> str:
    form = str(relation_form or "").strip().lower()
    if form == "nonlinear":
        return "nonlinear"
    d = str(direction or "").strip().lower()
    if d == "negative":
        return "negative"
    if d == "positive":
        return "positive"
    if d in {"u_shape", "u_shaped", "inverted_u", "non_directional", "non_significant"}:
        return "nonlinear"
    return "nonlinear"


def _fetch_all(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(dict(zip(cols, row)))
        return out


def main() -> None:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Run: uv add psycopg[binary]")

    args = parse_args()
    with psycopg.connect(args.dsn) as conn:
        papers_rows = _fetch_all(conn, "SELECT paper_id FROM papers ORDER BY paper_id")
        rel_rows = _fetch_all(
            conn,
            """
            SELECT
              id AS relation_row_id,
              paper_id, source_var, target_var,
              source_canonical_var_id, target_canonical_var_id,
              source_alias_text, target_alias_text,
              relation_type, model_tag, relation_form, direction, verification, evidence_anchor
            FROM relations
            ORDER BY paper_id
            """,
        )
        domain_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, domain
            FROM paper_domains
            ORDER BY paper_id, domain
            """,
        )
        alias_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, relation_row_id, canonical_var_id, alias_text, role
            FROM alias_mentions
            ORDER BY paper_id, relation_row_id, role
            """,
        )
        hyp_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, label, statement, verification, evidence_anchor
            FROM hypotheses
            ORDER BY paper_id
            """,
        )
        vtg_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, variable_name, theory, evidence_anchor
            FROM variable_theory_grounding
            ORDER BY paper_id
            """,
        )
        rtg_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, source_var, target_var, theory, evidence_anchor
            FROM relation_theory_grounding
            ORDER BY paper_id
            """,
        )
        cite_rows = _fetch_all(
            conn,
            """
            SELECT paper_id, citation_key, source_text, evidence_anchor
            FROM citations
            ORDER BY paper_id
            """,
        )

    variable_nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    papers_map: dict[str, dict[str, Any]] = {}

    for p in papers_rows:
        paper_id = str(p.get("paper_id", "")).strip()
        if not paper_id:
            continue
        papers_map[paper_id] = {
            "paper_id": paper_id,
            "doi": paper_id,
            "paper_domains": [],
            "relations": [],
            "hypotheses": [],
            "variable_level_theory_grounding": [],
            "relation_level_theory_grounding": [],
            "citations": [],
        }

    domains_by_paper: dict[str, list[str]] = {}
    for row in domain_rows:
        pid = str(row.get("paper_id", "")).strip()
        domain = str(row.get("domain", "")).strip()
        if not pid or not domain:
            continue
        domains_by_paper.setdefault(pid, [])
        if domain not in domains_by_paper[pid]:
            domains_by_paper[pid].append(domain)

    alias_by_relation: dict[tuple[str, int], dict[str, list[str]]] = {}
    for row in alias_rows:
        pid = str(row.get("paper_id", "")).strip()
        rid = int(row.get("relation_row_id") or 0)
        role = str(row.get("role", "")).strip().lower()
        alias = str(row.get("alias_text", "")).strip()
        if not pid or not rid or role not in {"source", "target"} or not alias:
            continue
        key = (pid, rid)
        alias_by_relation.setdefault(key, {"source": [], "target": []})
        if alias not in alias_by_relation[key][role]:
            alias_by_relation[key][role].append(alias)

    for rel in rel_rows:
        paper_id = str(rel.get("paper_id", "")).strip()
        source = str(rel.get("source_var", "")).strip()
        target = str(rel.get("target_var", "")).strip()
        if not paper_id or not source or not target:
            continue
        source_id = str(rel.get("source_canonical_var_id", "")).strip() or f"var::{_slug(source)}"
        target_id = str(rel.get("target_canonical_var_id", "")).strip() or f"var::{_slug(target)}"
        variable_nodes.setdefault(source_id, {"id": source_id, "type": "variable", "label": source, "name": source})
        variable_nodes.setdefault(target_id, {"id": target_id, "type": "variable", "label": target, "name": target})
        relation_row_id = int(rel.get("relation_row_id") or 0)
        alias_pair = alias_by_relation.get((paper_id, relation_row_id), {"source": [], "target": []})

        rel_payload = {
            "source_var": source,
            "target_var": target,
            "source_aliases": list(alias_pair["source"]) or [str(rel.get("source_alias_text", "")).strip() or source],
            "target_aliases": list(alias_pair["target"]) or [str(rel.get("target_alias_text", "")).strip() or target],
            "source_canonical_var_id": source_id,
            "target_canonical_var_id": target_id,
            "relation_type": str(rel.get("relation_type", "") or ""),
            "model_tag": str(rel.get("model_tag", "") or ""),
            "relation_form": str(rel.get("relation_form", "") or "linear"),
            "direction": str(rel.get("direction", "") or ""),
            "verification": str(rel.get("verification", "") or ""),
            "evidence_anchor": str(rel.get("evidence_anchor", "") or ""),
        }
        papers_map.setdefault(
            paper_id,
            {
                "paper_id": paper_id,
                "doi": paper_id,
                "paper_domains": [],
                "relations": [],
                "hypotheses": [],
                "variable_level_theory_grounding": [],
                "relation_level_theory_grounding": [],
                "citations": [],
            },
        )["relations"].append(rel_payload)

        edges.append(
            {
                "id": f"edge::{_slug(paper_id)}::{_slug(source)}::{_slug(target)}::{len(edges)}",
                "source": source_id,
                "target": target_id,
                "paper_id": paper_id,
                "doi": paper_id,
                "relation_type": rel_payload["relation_type"],
                "relation_form": rel_payload["relation_form"],
                "direction": rel_payload["direction"],
                "display_effect_class": _display_effect_class(rel_payload["direction"], rel_payload["relation_form"]),
                "verification": rel_payload["verification"],
                "strength": _strength_from_verification(rel_payload["verification"]),
                "evidence_anchor": rel_payload["evidence_anchor"],
            }
        )

    for row in hyp_rows:
        pid = str(row.get("paper_id", "")).strip()
        if not pid:
            continue
        papers_map.setdefault(
            pid,
            {
                "paper_id": pid,
                "doi": pid,
                "paper_domains": [],
                "relations": [],
                "hypotheses": [],
                "variable_level_theory_grounding": [],
                "relation_level_theory_grounding": [],
                "citations": [],
            },
        )["hypotheses"].append(
            {
                "label": str(row.get("label", "") or ""),
                "statement": str(row.get("statement", "") or ""),
                "verification": str(row.get("verification", "") or ""),
                "evidence_anchor": str(row.get("evidence_anchor", "") or ""),
            }
        )

    for row in vtg_rows:
        pid = str(row.get("paper_id", "")).strip()
        if not pid:
            continue
        papers_map.setdefault(
            pid,
            {
                "paper_id": pid,
                "doi": pid,
                "paper_domains": [],
                "relations": [],
                "hypotheses": [],
                "variable_level_theory_grounding": [],
                "relation_level_theory_grounding": [],
                "citations": [],
            },
        )["variable_level_theory_grounding"].append(
            {
                "variable": str(row.get("variable_name", "") or ""),
                "theory": str(row.get("theory", "") or ""),
                "evidence_anchor": str(row.get("evidence_anchor", "") or ""),
            }
        )

    for row in rtg_rows:
        pid = str(row.get("paper_id", "")).strip()
        if not pid:
            continue
        papers_map.setdefault(
            pid,
            {
                "paper_id": pid,
                "doi": pid,
                "paper_domains": [],
                "relations": [],
                "hypotheses": [],
                "variable_level_theory_grounding": [],
                "relation_level_theory_grounding": [],
                "citations": [],
            },
        )["relation_level_theory_grounding"].append(
            {
                "source_var": str(row.get("source_var", "") or ""),
                "target_var": str(row.get("target_var", "") or ""),
                "theory": str(row.get("theory", "") or ""),
                "evidence_anchor": str(row.get("evidence_anchor", "") or ""),
            }
        )

    for row in cite_rows:
        pid = str(row.get("paper_id", "")).strip()
        if not pid:
            continue
        papers_map.setdefault(
            pid,
            {
                "paper_id": pid,
                "doi": pid,
                "paper_domains": [],
                "relations": [],
                "hypotheses": [],
                "variable_level_theory_grounding": [],
                "relation_level_theory_grounding": [],
                "citations": [],
            },
        )["citations"].append(
            {
                "citation_key": str(row.get("citation_key", "") or ""),
                "source_text": str(row.get("source_text", "") or ""),
                "evidence_anchor": str(row.get("evidence_anchor", "") or ""),
            }
        )

    papers = list(papers_map.values())
    for p in papers:
        pid = str(p.get("paper_id", "")).strip()
        p["paper_domains"] = domains_by_paper.get(pid, [])
    artifact = {
        "meta": {
            "total_rows": len(papers),
            "success_rows": len(papers),
            "failed_rows": 0,
            "node_count": len(variable_nodes),
            "edge_count": len(edges),
            "paper_count": len(papers),
        },
        "nodes": list(variable_nodes.values()),
        "edges": edges,
        "papers": papers,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output_json), "meta": artifact["meta"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
