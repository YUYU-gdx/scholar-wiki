from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any

logger = logging.getLogger(__name__)


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


def _canonical_var_id(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    return f"var::{value}" if value else "var::unknown"


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export extraction outputs to frontend-friendly graph artifact.")
    parser.add_argument("--raw-output-jsonl", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def run_export(
    input_json: Path,
    output_json: Path | None = None,
) -> Path | None:
    if output_json is None:
        output_json = input_json.parent / "frontend_artifact.json"
    try:
        extractor = _load_extractor_module()
    except Exception as exc:
        logger.warning("Export setup failed: %s", exc)
        return None

    variable_nodes: dict[str, dict[str, Any]] = {}
    node_aliases: dict[str, set[str]] = {}
    edges: list[dict[str, Any]] = []
    moderation_links: list[dict[str, Any]] = []
    interaction_links: list[dict[str, Any]] = []
    papers: list[dict[str, Any]] = []
    edge_key_seen: set[str] = set()

    total = 0
    success = 0
    failed = 0

    for row in _iter_jsonl(input_json):
        total += 1
        if str(row.get("status", "")).strip() != "ok":
            failed += 1
            continue

        raw_response = str(row.get("raw_response", "") or "")
        try:
            bundle = extractor.parse_extraction_response(raw_response)
        except Exception:
            failed += 1
            continue

        success += 1
        paper_id = str(row.get("paper_id", "")).strip()
        doi = str(row.get("doi", "")).strip()
        paper_payload = {
            "paper_id": paper_id,
            "doi": doi,
            "offline_html_path": str(row.get("offline_html_path", "") or ""),
            "article_url": str(row.get("article_url", "") or ""),
            "publication_date": str(row.get("publication_date", "") or ""),
            "online_date": str(row.get("online_date", "") or ""),
            "publication_year": _coerce_optional_int(row.get("publication_year") or row.get("pub_year") or row.get("year")),
            "paper_citation_count": _coerce_optional_int(row.get("paper_citation_count") or row.get("citation_count")),
            "paper_domains": list(getattr(bundle, "paper_domains", [])),
            "extractability_status": bundle.extractability_status,
            "paper_type": bundle.paper_type,
            "extractability_reason": bundle.extractability_reason,
            "extractability_evidence_section": bundle.extractability_evidence_section,
            "direct_effects": list(bundle.direct_effects),
            "interactions": list(bundle.interactions),
            "variable_definitions": list(bundle.variable_definitions),
        }
        papers.append(paper_payload)

        for rel in bundle.direct_effects:
            source = str(rel.get("source", "")).strip()
            target = str(rel.get("target", "")).strip()
            if not source or not target:
                continue
            source_id = _canonical_var_id(source)
            target_id = _canonical_var_id(target)
            _ensure_node(variable_nodes, node_aliases, source_id, source, [])
            _ensure_node(variable_nodes, node_aliases, target_id, target, [])

            effect_form = str(rel.get("effect_form", "") or "").strip().lower()
            evidence_text = str(rel.get("evidence_text", "") or "").strip()

            dedupe_key = f"{paper_id}|{source_id}|{target_id}|{evidence_text}"
            if dedupe_key in edge_key_seen:
                continue
            edge_key_seen.add(dedupe_key)
            edges.append(
                {
                    "id": f"edge::{_slug(paper_id)}::{_slug(source)}::{_slug(target)}::{len(edges)}",
                    "source": source_id,
                    "target": target_id,
                    "source_name_local": source,
                    "target_name_local": target,
                    "paper_id": paper_id,
                    "doi": doi,
                    "effect_form": effect_form,
                    "theory_name": str(rel.get("theory_name", "") or "").strip(),
                    "verification": str(rel.get("verification", "") or ""),
                    "evidence_text": evidence_text,
                    "paper_year": paper_payload.get("publication_year"),
                    "display_effect_class": effect_form or "unclear",
                }
            )

        for rel in bundle.moderations:
            moderator = str(rel.get("moderator", "")).strip()
            source = str(rel.get("source", "")).strip()
            target = str(rel.get("target", "")).strip()
            if not moderator or not source or not target:
                continue
            moderator_id = _canonical_var_id(moderator)
            source_id = _canonical_var_id(source)
            target_id = _canonical_var_id(target)
            _ensure_node(variable_nodes, node_aliases, moderator_id, moderator, [])
            _ensure_node(variable_nodes, node_aliases, source_id, source, [])
            _ensure_node(variable_nodes, node_aliases, target_id, target, [])

            moderation_links.append(
                {
                    "id": f"mod::{_slug(paper_id)}::{_slug(moderator)}::{len(moderation_links)}",
                    "paper_id": paper_id,
                    "doi": doi,
                    "moderator_var": moderator,
                    "moderator_node_id": moderator_id,
                    "moderated_relation": {
                        "source_var": source,
                        "target_var": target,
                        "source_node_id": source_id,
                        "target_node_id": target_id,
                    },
                    "effect_form": str(rel.get("effect_form", "") or "").strip().lower(),
                    "theory_name": str(rel.get("theory_name", "") or "").strip(),
                    "verification": str(rel.get("verification", "") or ""),
                    "evidence_text": str(rel.get("evidence_text", "") or ""),
                    "paper_year": paper_payload.get("publication_year"),
                }
            )

        for rel in bundle.interactions:
            inputs = list(rel.get("inputs", []) or [])
            output = str(rel.get("output", "") or "").strip()
            if len(inputs) < 2 or not output:
                continue
            output_id = _canonical_var_id(output)
            _ensure_node(variable_nodes, node_aliases, output_id, output, [])

            resolved_input_ids: list[str] = []
            resolved_input_names: list[str] = []
            for input_name in inputs:
                in_name = str(input_name or "").strip()
                if not in_name:
                    continue
                in_id = _canonical_var_id(in_name)
                _ensure_node(variable_nodes, node_aliases, in_id, in_name, [])
                resolved_input_ids.append(in_id)
                resolved_input_names.append(in_name)

            if len(resolved_input_ids) < 2:
                continue

            interaction_links.append(
                {
                    "id": f"int::{_slug(paper_id)}::{len(interaction_links)}",
                    "paper_id": paper_id,
                    "doi": doi,
                    "inputs": resolved_input_names,
                    "input_node_ids": resolved_input_ids,
                    "output": output,
                    "output_node_id": output_id,
                    "effect_form": str(rel.get("effect_form", "") or "").strip().lower(),
                    "theory_name": str(rel.get("theory_name", "") or "").strip(),
                    "verification": str(rel.get("verification", "") or ""),
                    "evidence_text": str(rel.get("evidence_text", "") or ""),
                    "paper_year": paper_payload.get("publication_year"),
                }
            )

    _fill_node_first_year(variable_nodes, edges)
    for node_id, aliases in node_aliases.items():
        node = variable_nodes.get(node_id)
        if node is not None:
            node["aliases"] = sorted(aliases)
            node["alias_count"] = len(aliases)

    out_payload = {
        "meta": {
            "total_rows": total,
            "success_rows": success,
            "failed_rows": failed,
            "node_count": len(variable_nodes),
            "edge_count": len(edges),
            "paper_count": len(papers),
            "interaction_count": len(interaction_links),
        },
        "nodes": list(variable_nodes.values()),
        "edges": edges,
        "moderation_links": moderation_links,
        "interaction_links": interaction_links,
        "papers": papers,
    }

    try:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write output to %s: %s", output_json, exc)
        return None

    print(json.dumps(out_payload["meta"], ensure_ascii=False, indent=2))
    return output_json


def main() -> None:
    args = parse_args()
    result = run_export(
        input_json=args.raw_output_jsonl,
        output_json=args.output_json,
    )
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
