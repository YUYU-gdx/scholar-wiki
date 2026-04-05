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


def _normalize_relation_type(value: str) -> str:
    t = str(value or "").strip().lower()
    if not t:
        return "unspecified"
    if "moder" in t:
        return "moderation"
    if "mediat" in t:
        return "mediation"
    if "direct" in t:
        return "direct"
    if "interact" in t:
        return "interaction"
    if "curv" in t or "nonlinear" in t or "u-sh" in t or "u_sh" in t:
        return "nonlinear_effect"
    return "other"


def _fetch_all(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            out.append(dict(zip(cols, row)))
        return out


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _normalize_alias(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", t).strip("-")
    return t


def _looks_like_abbreviation(text: str) -> bool:
    token = str(text or "").strip()
    return bool(re.fullmatch(r"[A-Z][A-Z0-9/&-]{1,7}", token))


class _Dsu:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        p = self.parent.get(x, x)
        if p != x:
            p = self.find(p)
            self.parent[x] = p
        else:
            self.parent[x] = x
        return p

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _choose_canonical_name(names: list[str]) -> str:
    cleaned = [str(n or "").strip() for n in names if str(n or "").strip()]
    if not cleaned:
        return "unknown"
    non_abbr = [n for n in cleaned if not _looks_like_abbreviation(n)]
    base = non_abbr if non_abbr else cleaned
    return sorted(base, key=lambda x: (len(x.split()), len(x), x.lower()), reverse=True)[0]


def main() -> None:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Run: uv add psycopg[binary]")

    args = parse_args()
    with psycopg.connect(args.dsn) as conn:
        try:
            papers_rows = _fetch_all(
                conn,
                """
                SELECT
                  paper_id,
                  doi,
                  offline_html_path,
                  article_url,
                  publication_date,
                  online_date,
                  publication_year,
                  paper_citation_count
                FROM papers
                ORDER BY paper_id
                """,
            )
        except Exception:
            papers_rows = _fetch_all(
                conn,
                """
                SELECT
                  paper_id,
                  doi,
                  publication_date,
                  online_date,
                  publication_year,
                  paper_citation_count
                FROM papers
                ORDER BY paper_id
                """,
            )
        try:
            rel_rows = _fetch_all(
                conn,
                """
                SELECT
                  id AS relation_row_id,
                  paper_id, source_var, target_var,
                  source_canonical_var_id, target_canonical_var_id,
                  source_alias_text, target_alias_text,
                  unresolved_abbr, abbr_form, name_resolution_source,
                  relation_type, relation_type_raw, relation_type_std, model_tag, relation_form, direction, verification, evidence_anchor,
                  moderator_var, mediator_var, condition_text, moderated_source_var, moderated_target_var, moderated_hypothesis_label
                FROM relations
                ORDER BY paper_id
                """,
            )
        except Exception:
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
    moderation_links: list[dict[str, Any]] = []
    papers_map: dict[str, dict[str, Any]] = {}
    alias_to_node_ids: dict[str, set[str]] = {}

    for p in papers_rows:
        paper_id = str(p.get("paper_id", "")).strip()
        if not paper_id:
            continue
        publication_year = _coerce_int(p.get("publication_year"))
        paper_citation_count = _coerce_int(p.get("paper_citation_count"))
        papers_map[paper_id] = {
            "paper_id": paper_id,
            "doi": str(p.get("doi", "") or paper_id),
            "offline_html_path": str(p.get("offline_html_path", "") or ""),
            "article_url": str(p.get("article_url", "") or ""),
            "publication_date": str(p.get("publication_date", "") or ""),
            "online_date": str(p.get("online_date", "") or ""),
            "publication_year": publication_year,
            "paper_citation_count": paper_citation_count,
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
        for alias in [source, *alias_pair.get("source", []), str(rel.get("source_alias_text", "") or "")]:
            norm = _normalize_alias(alias)
            if norm:
                alias_to_node_ids.setdefault(norm, set()).add(source_id)
        for alias in [target, *alias_pair.get("target", []), str(rel.get("target_alias_text", "") or "")]:
            norm = _normalize_alias(alias)
            if norm:
                alias_to_node_ids.setdefault(norm, set()).add(target_id)
        paper_obj = papers_map.get(paper_id, {})
        paper_year = _coerce_int(paper_obj.get("publication_year"))
        paper_citation_count = _coerce_int(paper_obj.get("paper_citation_count"))

        rel_payload = {
            "source_var": source,
            "target_var": target,
            "source_aliases": list(alias_pair["source"]) or [str(rel.get("source_alias_text", "")).strip() or source],
            "target_aliases": list(alias_pair["target"]) or [str(rel.get("target_alias_text", "")).strip() or target],
            "source_canonical_var_id": source_id,
            "target_canonical_var_id": target_id,
            "unresolved_abbr": bool(rel.get("unresolved_abbr", False)),
            "abbr_form": str(rel.get("abbr_form", "") or ""),
            "name_resolution_source": str(rel.get("name_resolution_source", "") or ""),
            "relation_type_raw": str(rel.get("relation_type_raw", "") or rel.get("relation_type", "") or ""),
            "relation_type_std": str(rel.get("relation_type_std", "") or _normalize_relation_type(str(rel.get("relation_type", "") or ""))),
            "relation_type": str(rel.get("relation_type_std", "") or _normalize_relation_type(str(rel.get("relation_type", "") or ""))),
            "model_tag": str(rel.get("model_tag", "") or ""),
            "relation_form": str(rel.get("relation_form", "") or "linear"),
            "direction": str(rel.get("direction", "") or ""),
            "verification": str(rel.get("verification", "") or ""),
            "evidence_anchor": str(rel.get("evidence_anchor", "") or ""),
            "moderator_var": str(rel.get("moderator_var", "") or ""),
            "mediator_var": str(rel.get("mediator_var", "") or ""),
            "condition_text": str(rel.get("condition_text", "") or ""),
            "moderated_relation": {
                "source_var": str(rel.get("moderated_source_var", "") or ""),
                "target_var": str(rel.get("moderated_target_var", "") or ""),
                "hypothesis_label": str(rel.get("moderated_hypothesis_label", "") or ""),
            },
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

        if rel_payload["relation_type_std"] == "moderation" and rel_payload["moderator_var"] and rel_payload["moderated_relation"]["source_var"] and rel_payload["moderated_relation"]["target_var"]:
            moderator_id = f"var::{_slug(rel_payload['moderator_var'])}"
            variable_nodes.setdefault(moderator_id, {"id": moderator_id, "type": "variable", "label": rel_payload["moderator_var"], "name": rel_payload["moderator_var"]})
            moderation_links.append(
                {
                    "id": f"mod::{_slug(paper_id)}::{_slug(rel_payload['moderator_var'])}::{len(moderation_links)}",
                    "paper_id": paper_id,
                    "doi": str(paper_obj.get("doi", "") or paper_id),
                    "moderator_var": rel_payload["moderator_var"],
                    "moderator_node_id": moderator_id,
                    "moderated_relation": rel_payload["moderated_relation"],
                    "condition_text": rel_payload["condition_text"],
                    "evidence_section": rel_payload["evidence_anchor"],
                    "paper_year": paper_year,
                }
            )
            continue

        edges.append(
            {
                "id": f"edge::{_slug(paper_id)}::{_slug(source)}::{_slug(target)}::{len(edges)}",
                "source": source_id,
                "target": target_id,
                "paper_id": paper_id,
                "doi": paper_id,
                "relation_type_raw": rel_payload["relation_type_raw"],
                "relation_type_std": rel_payload["relation_type_std"],
                "relation_type": rel_payload["relation_type_std"],
                "relation_form": rel_payload["relation_form"],
                "direction": rel_payload["direction"],
                "display_effect_class": _display_effect_class(rel_payload["direction"], rel_payload["relation_form"]),
                "verification": rel_payload["verification"],
                "strength": _strength_from_verification(rel_payload["verification"]),
                "evidence_anchor": rel_payload["evidence_anchor"],
                "evidence_section": rel_payload["evidence_anchor"],
                "paper_year": paper_year,
                "citation_stats": {"paper_citation_count": paper_citation_count},
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

    dsu = _Dsu()
    for node_id in variable_nodes:
        dsu.find(node_id)
    for node_ids in alias_to_node_ids.values():
        node_list = sorted(node_ids)
        if len(node_list) < 2:
            continue
        head = node_list[0]
        for nid in node_list[1:]:
            dsu.union(head, nid)

    groups: dict[str, list[str]] = {}
    for nid in variable_nodes:
        groups.setdefault(dsu.find(nid), []).append(nid)

    remap: dict[str, str] = {}
    merged_nodes: dict[str, dict[str, Any]] = {}
    for members in groups.values():
        names = [str(variable_nodes[m].get("label", "") or variable_nodes[m].get("name", "") or "") for m in members]
        canonical_name = _choose_canonical_name(names)
        canonical_id = f"var::{_slug(canonical_name)}"
        merged_nodes.setdefault(
            canonical_id,
            {"id": canonical_id, "type": "variable", "label": canonical_name, "name": canonical_name},
        )
        for old in members:
            remap[old] = canonical_id

    for edge in edges:
        edge["source"] = remap.get(str(edge.get("source", "")), str(edge.get("source", "")))
        edge["target"] = remap.get(str(edge.get("target", "")), str(edge.get("target", "")))
    for m in moderation_links:
        old_mid = str(m.get("moderator_node_id", "")).strip()
        m["moderator_node_id"] = remap.get(old_mid, old_mid)
        new_mid = str(m.get("moderator_node_id", "")).strip()
        node = merged_nodes.get(new_mid)
        if node is not None:
            m["moderator_var"] = str(node.get("label", "") or m.get("moderator_var", ""))
    for paper in papers:
        relations = list(paper.get("relations", []) or [])
        for rel in relations:
            src_old = str(rel.get("source_canonical_var_id", "")).strip() or f"var::{_slug(str(rel.get('source_var', '')))}"
            tgt_old = str(rel.get("target_canonical_var_id", "")).strip() or f"var::{_slug(str(rel.get('target_var', '')))}"
            src_new = remap.get(src_old, src_old)
            tgt_new = remap.get(tgt_old, tgt_old)
            rel["source_canonical_var_id"] = src_new
            rel["target_canonical_var_id"] = tgt_new
            if src_new in merged_nodes:
                rel["source_var"] = str(merged_nodes[src_new].get("label", "") or rel.get("source_var", ""))
            if tgt_new in merged_nodes:
                rel["target_var"] = str(merged_nodes[tgt_new].get("label", "") or rel.get("target_var", ""))

    edge_years_by_node: dict[str, list[int]] = {}
    citation_by_node: dict[str, list[int]] = {}
    all_years: list[int] = []
    for edge in edges:
        src = str(edge.get("source", "")).strip()
        tgt = str(edge.get("target", "")).strip()
        year = _coerce_int(edge.get("paper_year"))
        paper_citation = _coerce_int((edge.get("citation_stats", {}) or {}).get("paper_citation_count"))
        if year is not None:
            edge_years_by_node.setdefault(src, []).append(year)
            edge_years_by_node.setdefault(tgt, []).append(year)
        if paper_citation is not None:
            citation_by_node.setdefault(src, []).append(paper_citation)
            citation_by_node.setdefault(tgt, []).append(paper_citation)
    for node_id, node in merged_nodes.items():
        years = edge_years_by_node.get(node_id, [])
        citations = citation_by_node.get(node_id, [])
        first_year = min(years) if years else None
        if first_year is not None:
            all_years.append(first_year)
        node["first_year"] = first_year
        node["citation_stats"] = {
            "max_citation_count": max(citations) if citations else None,
            "mean_citation_count": (sum(citations) / len(citations)) if citations else None,
        }

    artifact = {
        "meta": {
            "total_rows": len(papers),
            "success_rows": len(papers),
            "failed_rows": 0,
            "node_count": len(merged_nodes),
            "edge_count": len(edges),
            "paper_count": len(papers),
            "year_range": {"min": min(all_years) if all_years else None, "max": max(all_years) if all_years else None},
        },
        "nodes": list(merged_nodes.values()),
        "edges": edges,
        "moderation_links": moderation_links,
        "papers": papers,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output_json), "meta": artifact["meta"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
