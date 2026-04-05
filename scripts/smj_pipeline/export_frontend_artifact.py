from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


def _load_extractor_module():
    module_path = Path(__file__).resolve().parent / "extraction" / "extractor.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_extraction_extractor_for_export", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load extractor module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                yield payload


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
    # Prefer richer phrase-like names as canonical display name.
    return sorted(base, key=lambda x: (len(x.split()), len(x), x.lower()), reverse=True)[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export extraction outputs to frontend-friendly graph artifact.")
    parser.add_argument(
        "--raw-output-jsonl",
        type=Path,
        required=True,
        help="raw_llm_outputs.jsonl from run_extraction_mvp",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="output frontend artifact json path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    extractor = _load_extractor_module()

    variable_nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    moderation_links: list[dict[str, Any]] = []
    papers: list[dict[str, Any]] = []
    alias_to_node_ids: dict[str, set[str]] = {}

    total = 0
    success = 0
    failed = 0

    for row in _iter_jsonl(args.raw_output_jsonl):
        total += 1
        status = str(row.get("status", "")).strip()
        paper_id = str(row.get("paper_id", "")).strip()
        doi = str(row.get("doi", "")).strip()

        if status != "ok":
            failed += 1
            continue

        raw_response = str(row.get("raw_response", "") or "")
        try:
            bundle = extractor.parse_extraction_response(raw_response)
        except Exception:
            failed += 1
            continue

        success += 1
        paper_payload = {
            "paper_id": paper_id,
            "doi": doi,
            "offline_html_path": str(row.get("offline_html_path", "") or ""),
            "article_url": str(row.get("article_url", "") or ""),
            "publication_date": str(row.get("publication_date", "") or row.get("pub_date", "") or ""),
            "online_date": str(row.get("online_date", "") or ""),
            "publication_year": _coerce_optional_int(row.get("publication_year") or row.get("pub_year") or row.get("year")),
            "paper_citation_count": _coerce_optional_int(row.get("paper_citation_count") or row.get("citation_count")),
            "paper_domains": list(getattr(bundle, "paper_domains", [])),
            "relations": bundle.relations,
            "hypotheses": bundle.hypotheses,
            "variable_level_theory_grounding": bundle.variable_level_theory_grounding,
            "relation_level_theory_grounding": bundle.relation_level_theory_grounding,
            "citations": bundle.citations,
        }
        papers.append(paper_payload)

        for rel in bundle.relations:
            source = str(rel.get("source_var", "")).strip()
            target = str(rel.get("target_var", "")).strip()
            if not source or not target:
                continue

            source_id = str(rel.get("source_canonical_var_id", "")).strip() or f"var::{_slug(source)}"
            target_id = str(rel.get("target_canonical_var_id", "")).strip() or f"var::{_slug(target)}"
            source_aliases = [source, *list(rel.get("source_aliases", []) or [])]
            target_aliases = [target, *list(rel.get("target_aliases", []) or [])]
            variable_nodes.setdefault(
                source_id,
                {"id": source_id, "type": "variable", "label": source, "name": source},
            )
            variable_nodes.setdefault(
                target_id,
                {"id": target_id, "type": "variable", "label": target, "name": target},
            )
            for alias in source_aliases:
                norm = _normalize_alias(alias)
                if norm:
                    alias_to_node_ids.setdefault(norm, set()).add(source_id)
            for alias in target_aliases:
                norm = _normalize_alias(alias)
                if norm:
                    alias_to_node_ids.setdefault(norm, set()).add(target_id)

            edge_id = f"edge::{_slug(paper_id)}::{_slug(source)}::{_slug(target)}::{len(edges)}"
            paper_year = _coerce_optional_int(paper_payload.get("publication_year"))
            paper_citations = _coerce_optional_int(paper_payload.get("paper_citation_count"))
            relation_type_std = str(rel.get("relation_type_std", "") or _normalize_relation_type(str(rel.get("relation_type", ""))))
            relation_type_raw = str(rel.get("relation_type_raw", "") or rel.get("relation_type", ""))
            moderated = rel.get("moderated_relation") if isinstance(rel.get("moderated_relation"), dict) else {}
            moderator_var = str(rel.get("moderator_var", "") or "").strip()
            if relation_type_std == "moderation" and moderator_var and str(moderated.get("source_var", "")).strip() and str(moderated.get("target_var", "")).strip():
                moderator_id = f"var::{_slug(moderator_var)}"
                variable_nodes.setdefault(
                    moderator_id,
                    {"id": moderator_id, "type": "variable", "label": moderator_var, "name": moderator_var},
                )
                moderation_links.append(
                    {
                        "id": f"mod::{_slug(paper_id)}::{_slug(moderator_var)}::{len(moderation_links)}",
                        "paper_id": paper_id,
                        "doi": doi,
                        "moderator_var": moderator_var,
                        "moderator_node_id": moderator_id,
                        "moderated_relation": {
                            "source_var": str(moderated.get("source_var", "") or ""),
                            "target_var": str(moderated.get("target_var", "") or ""),
                            "hypothesis_label": str(moderated.get("hypothesis_label", "") or ""),
                        },
                        "condition_text": str(rel.get("condition_text", "") or ""),
                        "evidence_section": rel.get("evidence_anchor", ""),
                        "paper_year": paper_year,
                    }
                )
                continue
            edges.append(
                {
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "paper_id": paper_id,
                    "doi": doi,
                    "relation_type_raw": relation_type_raw,
                    "relation_type_std": relation_type_std,
                    "relation_type": relation_type_std,
                    "unresolved_abbr": bool(rel.get("unresolved_abbr", False)),
                    "abbr_form": str(rel.get("abbr_form", "") or ""),
                    "name_resolution_source": str(rel.get("name_resolution_source", "") or ""),
                    "relation_form": rel.get("relation_form", "linear"),
                    "direction": rel.get("direction", ""),
                    "display_effect_class": _display_effect_class(
                        str(rel.get("direction", "")),
                        str(rel.get("relation_form", "linear")),
                    ),
                    "verification": rel.get("verification", ""),
                    "strength": _strength_from_verification(str(rel.get("verification", ""))),
                    "evidence_anchor": rel.get("evidence_anchor", ""),
                    "evidence_section": rel.get("evidence_anchor", ""),
                    "paper_year": paper_year,
                    "citation_stats": {"paper_citation_count": paper_citations},
                }
            )
    # Global synonym merge: node IDs connected by shared alias collapse into one point.
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
        year = _coerce_optional_int(edge.get("paper_year"))
        paper_citation = _coerce_optional_int((edge.get("citation_stats", {}) or {}).get("paper_citation_count"))
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
            "total_rows": total,
            "success_rows": success,
            "failed_rows": failed,
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
