from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any
import re

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    t = re.sub(r"[^a-z0-9一-鿿]+", "-", t).strip("-")
    return t or "unknown"


def _canonical_var_id(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    return f"var::{value}" if value else "var::unknown"


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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build optimized graph views from SQLite source-of-truth.")
    p.add_argument(
        "--db-path",
        type=Path,
        help="Path to the SQLite database file. Required unless --input-json is provided.",
    )
    p.add_argument(
        "--input-json",
        type=Path,
        help="Path to a pre-built frontend_artifact.json. Optional fallback.",
    )
    p.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Destination path for graph_views.json. Defaults next to the data source.",
    )
    p.add_argument("--overview-limit", type=int, default=700)
    return p.parse_args()


def _build_position(i: int, n: int, radius: float = 180.0) -> tuple[float, float, float]:
    if n <= 1:
        return (0.0, 0.0, 0.0)
    phi = math.pi * (3.0 - math.sqrt(5.0))
    y = 1.0 - (2.0 * i) / (n - 1)
    r = math.sqrt(max(0.0, 1.0 - y * y))
    theta = phi * i
    x = math.cos(theta) * r
    z = math.sin(theta) * r
    return (x * radius, y * radius, z * radius)


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


def _entropy_from_counts(counts: list[int]) -> float:
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    probs = [c / total for c in counts if c > 0]
    if len(probs) <= 1:
        return 0.0
    h = -sum(p * math.log(p) for p in probs)
    h_max = math.log(len(probs))
    if h_max <= 0:
        return 0.0
    return round(h / h_max, 6)


def _build_artifact_from_sqlite(db_path: Path) -> dict[str, Any]:
    """Query SQLite and produce a frontend-artifact dict.

    This is the single source-of-truth path: all paper, node, edge, and
    relation data is read exclusively from the SQLite database.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        # ── papers ──
        cur.execute(
            """
            SELECT paper_id, doi, title, authors_json, abstract, journal,
                   offline_html_path, source_pdf_path, source_md_path, source_html_path,
                   article_url, publication_date, online_date,
                   publication_year, paper_citation_count,
                   extractability_status, paper_type, extractability_reason, extractability_evidence_section
            FROM papers ORDER BY paper_id
            """
        )
        papers = [dict(r) for r in cur.fetchall()]

        # ── domains per paper ──
        cur.execute("SELECT paper_id, domain FROM paper_domains ORDER BY paper_id, id")
        domain_map: dict[str, list[str]] = {}
        for r in cur.fetchall():
            domain_map.setdefault(r["paper_id"], []).append(r["domain"])

        # ── variable definitions ──
        cur.execute(
            "SELECT paper_id, variable_name, aliases_json, definition_text, measurement_text FROM variable_definitions ORDER BY paper_id, id"
        )
        var_defs: dict[str, list[dict[str, Any]]] = {}
        for r in cur.fetchall():
            var_defs.setdefault(r["paper_id"], []).append(
                {
                    "variable": r["variable_name"],
                    "definition": r["definition_text"],
                    "measurement": r["measurement_text"],
                    "aliases": _loads_json_list(r["aliases_json"]),
                }
            )

        # ── direct effects ──
        cur.execute(
            """
            SELECT paper_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id,
                   source_alias_json, target_alias_json, effect_form, theory_name, verification, evidence_text
            FROM direct_effects ORDER BY paper_id, id
            """
        )
        effects = [dict(r) for r in cur.fetchall()]

        # ── moderations ──
        cur.execute(
            """
            SELECT paper_id, moderator_var, moderator_canonical_var_id, moderator_alias_json,
                   source_var, target_var, source_canonical_var_id, target_canonical_var_id,
                   effect_form, theory_name, verification, evidence_text
            FROM moderations ORDER BY paper_id, id
            """
        )
        moderations = [dict(r) for r in cur.fetchall()]

        # ── interactions ──
        cur.execute(
            """
            SELECT i.id, i.paper_id, i.output_var, i.output_canonical_var_id,
                   i.effect_form, i.theory_name, i.verification, i.evidence_text,
                   inp.input_var, inp.input_canonical_var_id, inp.input_order
            FROM interactions i
            LEFT JOIN interaction_inputs inp ON inp.interaction_id = i.id
            ORDER BY i.paper_id, i.id, inp.input_order
            """
        )
        inter_rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    # ── node / edge construction ──
    variable_nodes: dict[str, dict[str, Any]] = {}
    node_aliases: dict[str, set[str]] = {}
    edges: list[dict[str, Any]] = []
    moderation_links: list[dict[str, Any]] = []
    interaction_links: list[dict[str, Any]] = []
    papers_map: dict[str, dict[str, Any]] = {}

    for p in papers:
        pid = p["paper_id"]
        papers_map[pid] = {
            "paper_id": pid,
            "doi": p.get("doi", pid),
            "title": p.get("title", "") or "",
            "authors_json": json.loads(p.get("authors_json", "[]") or "[]"),
            "abstract": p.get("abstract", "") or "",
            "journal": p.get("journal", "") or "",
            "offline_html_path": p.get("offline_html_path", "") or "",
            "source_pdf_path": p.get("source_pdf_path", "") or "",
            "source_md_path": p.get("source_md_path", "") or "",
            "source_html_path": p.get("source_html_path", "") or "",
            "article_url": p.get("article_url", "") or "",
            "publication_date": p.get("publication_date", "") or "",
            "online_date": p.get("online_date", "") or "",
            "publication_year": p.get("publication_year"),
            "paper_citation_count": p.get("paper_citation_count"),
            "extractability_status": p.get("extractability_status", "") or "",
            "paper_type": p.get("paper_type", "") or "",
            "extractability_reason": p.get("extractability_reason", "") or "",
            "extractability_evidence_section": p.get("extractability_evidence_section", "") or "",
            "paper_domains": domain_map.get(pid, []),
            "variable_definitions": var_defs.get(pid, []),
            "main_effects": [],
            "moderations": [],
            "interactions": [],
        }

    for eff in effects:
        pid = eff["paper_id"]
        src = eff["source_var"]
        tgt = eff["target_var"]
        if pid not in papers_map or not src or not tgt:
            continue
        sid = eff["source_canonical_var_id"]
        tid = eff["target_canonical_var_id"]
        src_aliases = _loads_json_list(eff.get("source_alias_json"))
        tgt_aliases = _loads_json_list(eff.get("target_alias_json"))
        variable_nodes.setdefault(sid, {"id": sid, "type": "variable", "label": src, "name": src})
        variable_nodes.setdefault(tid, {"id": tid, "type": "variable", "label": tgt, "name": tgt})
        node_aliases.setdefault(sid, set()).update(a for a in src_aliases if a)
        node_aliases.setdefault(tid, set()).update(a for a in tgt_aliases if a)
        papers_map[pid]["main_effects"].append(
            {
                "from": src, "to": tgt,
                "effect": eff.get("effect_form", ""),
                "verification": eff.get("verification", ""),
                "evidence_snippet": eff.get("evidence_text", ""),
            }
        )
        edges.append(
            {
                "id": f"edge::{_slug(pid)}::{len(edges)}",
                "source": sid, "target": tid,
                "source_name_local": src, "target_name_local": tgt,
                "paper_id": pid,
                "relation_type": "main_effect",
                "relation_type_std": "main_effect",
                "relation_form": eff.get("effect_form", ""),
                "verification": eff.get("verification", ""),
                "evidence_snippet": eff.get("evidence_text", ""),
                "display_effect_class": "nonlinear",
            }
        )

    for mod in moderations:
        pid = mod["paper_id"]
        if pid not in papers_map:
            continue
        mid = mod["moderator_canonical_var_id"]
        moderator = mod["moderator_var"]
        variable_nodes.setdefault(mid, {"id": mid, "type": "variable", "label": moderator, "name": moderator})
        src_id = mod.get("source_canonical_var_id", "")
        tgt_id = mod.get("target_canonical_var_id", "")
        src = mod.get("source_var", "")
        tgt = mod.get("target_var", "")
        if src_id:
            variable_nodes.setdefault(src_id, {"id": src_id, "type": "variable", "label": src, "name": src})
        if tgt_id:
            variable_nodes.setdefault(tgt_id, {"id": tgt_id, "type": "variable", "label": tgt, "name": tgt})
        mod_aliases = _loads_json_list(mod.get("moderator_alias_json"))
        if mod_aliases:
            node_aliases.setdefault(mid, set()).update(a for a in mod_aliases if a)
        moderation_links.append(
            {
                "id": f"mod::{_slug(pid)}::{len(moderation_links)}",
                "paper_id": pid,
                "moderator_var": moderator,
                "moderator_node_id": mid,
                "moderated_relation": {
                    "source_var": src, "target_var": tgt,
                    "source_node_id": src_id, "target_node_id": tgt_id,
                },
                "direction": mod.get("effect_form", ""),
                "verification": mod.get("verification", ""),
                "evidence_snippet": mod.get("evidence_text", ""),
            }
        )

    grouped_inter: dict[tuple[str, int], dict[str, Any]] = {}
    for row in inter_rows:
        iid = int(row.get("id") or 0)
        pid = row["paper_id"]
        if iid <= 0 or pid not in papers_map:
            continue
        key = (pid, iid)
        if key not in grouped_inter:
            grouped_inter[key] = {
                "paper_id": pid,
                "output_var": row.get("output_var", ""),
                "output_canonical_var_id": row.get("output_canonical_var_id", ""),
                "effect_form": row.get("effect_form", ""),
                "verification": row.get("verification", ""),
                "evidence_text": row.get("evidence_text", ""),
                "inputs": [],
                "input_canonical_var_ids": [],
            }
        iv = (row.get("input_var") or "").strip()
        icv = (row.get("input_canonical_var_id") or "").strip()
        if iv:
            grouped_inter[key]["inputs"].append(iv)
        if icv:
            grouped_inter[key]["input_canonical_var_ids"].append(icv)

    for g in grouped_inter.values():
        pid = g["paper_id"]
        out = g["output_var"]
        out_id = g["output_canonical_var_id"]
        if out_id:
            variable_nodes.setdefault(out_id, {"id": out_id, "type": "variable", "label": out, "name": out})
        for iv, icv in zip(g["inputs"], g["input_canonical_var_ids"]):
            if icv:
                variable_nodes.setdefault(icv, {"id": icv, "type": "variable", "label": iv, "name": iv})
        interaction_links.append(
            {
                "id": f"int::{_slug(pid)}::{len(interaction_links)}",
                "paper_id": pid,
                "inputs": g["inputs"],
                "input_node_ids": g["input_canonical_var_ids"],
                "output": out,
                "output_node_id": out_id,
                "effect": g["effect_form"],
                "verification": g["verification"],
                "evidence_snippet": g["evidence_text"],
            }
        )

    # ── ensure variable nodes from definitions (even without edges) ──
    for pid, defs in var_defs.items():
        for vd in defs:
            cid = _canonical_var_id(vd["variable"])
            variable_nodes.setdefault(cid, {"id": cid, "type": "variable", "label": vd["variable"], "name": vd["variable"]})
            vd_aliases = vd.get("aliases", [])
            if vd_aliases:
                node_aliases.setdefault(cid, set()).update(a for a in vd_aliases if a)

    # ── compute first-year per node ──
    years_by_node: dict[str, list[int]] = {}
    for edge in edges:
        paper = papers_map.get(edge["paper_id"], {})
        year = _coerce_int(paper.get("publication_year"))
        if year is None:
            continue
        for key in ("source", "target"):
            nid = edge.get(key, "")
            if nid:
                years_by_node.setdefault(nid, []).append(year)
    for nid, node in variable_nodes.items():
        ys = years_by_node.get(nid, [])
        if ys:
            node["first_year"] = min(ys)

    for nid, aliases in node_aliases.items():
        node = variable_nodes.get(nid)
        if node is not None:
            node["aliases"] = sorted(aliases)
            node["alias_count"] = len(aliases)

    # ── merge variable definitions into nodes ──
    for pid, defs in var_defs.items():
        for vd in defs:
            cid = _canonical_var_id(vd["variable"])
            node = variable_nodes.get(cid)
            if node is not None:
                node.setdefault("definition", vd.get("definition", ""))
                node.setdefault("measurement", vd.get("measurement", ""))
                node.setdefault("aliases_from_paper", vd.get("aliases", []))

    return {
        "meta": {
            "paper_count": len(papers),
            "node_count": len(variable_nodes),
            "edge_count": len(edges),
        },
        "nodes": list(variable_nodes.values()),
        "edges": edges,
        "moderation_links": moderation_links,
        "interaction_links": interaction_links,
        "papers": list(papers_map.values()),
        "var_defs": var_defs,
    }


def run_build_from_artifact(data: dict[str, Any], output_json: Path) -> Path:
    """Build graph_views.json from an already-loaded artifact dict."""
    overview_limit = 700

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    moderation_links = data.get("moderation_links", [])
    interaction_links = data.get("interaction_links", [])
    papers = data.get("papers", [])

    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node.get("id", "")).strip()
        if not node_id:
            continue
        node_map[node_id] = dict(node)

    edge_index_by_node: dict[str, list[int]] = {}
    degree: dict[str, int] = {}
    for idx, edge in enumerate(edges):
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if not s or not t:
            continue
        edge_index_by_node.setdefault(s, []).append(idx)
        edge_index_by_node.setdefault(t, []).append(idx)
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1

    node_paper_counts: dict[str, dict[str, int]] = {}
    for edge in edges:
        pid = str(edge.get("paper_id", "")).strip()
        if not pid:
            continue
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if s:
            d = node_paper_counts.setdefault(s, {})
            d[pid] = d.get(pid, 0) + 1
        if t:
            d = node_paper_counts.setdefault(t, {})
            d[pid] = d.get(pid, 0) + 1
    for mod in moderation_links:
        pid = str(mod.get("paper_id", "")).strip()
        if not pid:
            continue
        mr = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
        ids = [
            str(mod.get("moderator_node_id", "")).strip(),
            str(mr.get("source_node_id", "")).strip(),
            str(mr.get("target_node_id", "")).strip(),
        ]
        for nid in ids:
            if not nid:
                continue
            d = node_paper_counts.setdefault(nid, {})
            d[pid] = d.get(pid, 0) + 1
    for inter in interaction_links:
        pid = str(inter.get("paper_id", "")).strip()
        if not pid:
            continue
        ids = [str(v).strip() for v in (inter.get("input_node_ids", []) or []) if str(v).strip()]
        out = str(inter.get("output_node_id", "")).strip()
        if out:
            ids.append(out)
        for nid in ids:
            d = node_paper_counts.setdefault(nid, {})
            d[pid] = d.get(pid, 0) + 1

    # Also count variable-definition associations (papers with no edges still own their vars)
    var_defs = data.get("var_defs", {}) if isinstance(data.get("var_defs"), dict) else {}
    for pid, defs in var_defs.items():
        for vd in defs:
            cid = _canonical_var_id(vd["variable"])
            d = node_paper_counts.setdefault(cid, {})
            d[pid] = d.get(pid, 0) + 1

    for node_id, node in node_map.items():
        profile = node_paper_counts.get(node_id, {})
        top_items = sorted(profile.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        node["paper_profile"] = {k: v for k, v in top_items}
        node["paper_count_mentions"] = int(sum(profile.values()))
        node["dominant_paper_id"] = top_items[0][0] if top_items else ""
        node["paper_entropy"] = _entropy_from_counts([v for _, v in top_items])

    year_by_node: dict[str, list[int]] = {}
    for edge in edges:
        year = _coerce_int(edge.get("paper_year"))
        if year is None:
            continue
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if s:
            year_by_node.setdefault(s, []).append(year)
        if t:
            year_by_node.setdefault(t, []).append(year)
    for node_id, node in node_map.items():
        if node.get("first_year") is None and node_id in year_by_node:
            node["first_year"] = min(year_by_node[node_id])

    variable_nodes = [n for n in node_map.values() if n.get("type") == "variable"]
    variable_nodes.sort(key=lambda n: degree.get(str(n.get("id", "")), 0), reverse=True)
    overview_nodes = variable_nodes[:overview_limit]
    overview_ids = {str(n["id"]) for n in overview_nodes}

    overview_edges: list[int] = []
    for idx, edge in enumerate(edges):
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if s in overview_ids and t in overview_ids:
            overview_edges.append(idx)

    for i, node in enumerate(overview_nodes):
        x, y, z = _build_position(i, len(overview_nodes))
        node["x"] = x
        node["y"] = y
        node["z"] = z

    paper_map: dict[str, dict[str, Any]] = {}
    for p in papers:
        paper_id = str(p.get("paper_id", "")).strip()
        doi = str(p.get("doi", "")).strip()
        if paper_id:
            paper_map[paper_id] = p
        if doi and doi not in paper_map:
            paper_map[doi] = p

    result = {
        "meta": dict(data.get("meta", {})),
        "nodes": node_map,
        "edges": edges,
        "moderation_links": moderation_links,
        "interaction_links": interaction_links,
        "edge_index_by_node": edge_index_by_node,
        "overview": {
            "node_ids": [str(n["id"]) for n in overview_nodes],
            "edge_indexes": overview_edges,
        },
        "paper_map": paper_map,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(output_json), "all_nodes": len(node_map), "all_edges": len(edges), "paper_count": len(paper_map)}, ensure_ascii=False, indent=2))
    return output_json


def main() -> None:
    args = parse_args()
    if args.db_path:
        data = _build_artifact_from_sqlite(args.db_path)
        output = args.output_json or args.db_path.parent / "graph_views.json"
        run_build_from_artifact(data, output)
    elif args.input_json:
        data = json.loads(args.input_json.read_text(encoding="utf-8"))
        output = args.output_json or args.input_json.parent / "graph_views.json"
        run_build_from_artifact(data, output)
    else:
        logger.error("Either --db-path or --input-json is required.")
        sys.exit(2)


if __name__ == "__main__":
    main()
