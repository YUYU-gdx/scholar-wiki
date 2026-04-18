from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

SUPPLY_CHAIN_ROOT = Path("outputs/smj_supply_chain_batch").resolve()


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


def _effect_to_direction_and_form(effect_raw: str) -> tuple[str, str, str]:
    raw = str(effect_raw or "").strip()
    t = raw.lower()
    if t in {"+", "positive"}:
        return "positive", "linear", ""
    if t in {"-", "negative"}:
        return "negative", "linear", ""
    if "nonlinear" in t or "u" in t or "curve" in t:
        return "nonlinear", "nonlinear", raw
    if t in {"mixed", "unclear"}:
        return t, "linear", ""
    return "unclear", "linear", raw if raw else ""


def _main_effect_from_direct(rel: dict[str, Any]) -> dict[str, Any]:
    direction = str(rel.get("direction", "") or "").strip().lower()
    relation_form = str(rel.get("relation_form", "") or "").strip().lower()
    effect = ""
    if relation_form == "nonlinear" or direction == "nonlinear":
        effect = "nonlinear"
    elif direction == "positive":
        effect = "+"
    elif direction == "negative":
        effect = "-"
    elif direction:
        effect = direction
    return {
        "from": str(rel.get("source", "") or "").strip(),
        "to": str(rel.get("target", "") or "").strip(),
        "effect": effect,
        "hypothesis_label": str(rel.get("hypothesis_label", "") or "").strip(),
        "verification": str(rel.get("verification", "") or "").strip(),
        "evidence_section": str(rel.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(rel.get("evidence_snippet", "") or "").strip(),
        "description": "",
    }


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
    parser.add_argument("--allow-non-supply-chain", action="store_true")
    return parser.parse_args()


def _enforce_supply_chain_path(path: Path, allow_non_supply_chain: bool, flag_name: str) -> None:
    resolved = path.resolve()
    if allow_non_supply_chain:
        return
    if SUPPLY_CHAIN_ROOT not in resolved.parents and resolved != SUPPLY_CHAIN_ROOT:
        raise RuntimeError(
            f"{flag_name} path is outside supply-chain scope: {resolved}\n"
            f"allowed root: {SUPPLY_CHAIN_ROOT}\n"
            "use --allow-non-supply-chain to override explicitly"
        )


def main() -> None:
    args = parse_args()
    _enforce_supply_chain_path(args.raw_output_jsonl, args.allow_non_supply_chain, "--raw-output-jsonl")
    _enforce_supply_chain_path(args.output_json, args.allow_non_supply_chain, "--output-json")
    extractor = _load_extractor_module()

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

    for row in _iter_jsonl(args.raw_output_jsonl):
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
            "main_effects": list(getattr(bundle, "main_effects", []))
            or [_main_effect_from_direct(x) for x in list(getattr(bundle, "direct_effects", []))],
            "interactions": bundle.interactions,
            "context_variables": list(getattr(bundle, "context_variables", [])),
            "operationalization": dict(getattr(bundle, "operationalization", {}) or {}),
            "variable_definitions": list(getattr(bundle, "variable_definitions", []) or []),
        }
        papers.append(paper_payload)

        for rel in paper_payload["main_effects"]:
            source = str(rel.get("from", "")).strip()
            target = str(rel.get("to", "")).strip()
            if not source or not target:
                continue
            source_id = _canonical_var_id(source)
            target_id = _canonical_var_id(target)
            _ensure_node(variable_nodes, node_aliases, source_id, source, [])
            _ensure_node(variable_nodes, node_aliases, target_id, target, [])
            direction, relation_form, relation_form_raw = _effect_to_direction_and_form(str(rel.get("effect", "") or ""))

            evidence = str(rel.get("evidence_section", "") or "").strip()
            rel_std = "main_effect"
            dedupe_key = f"{paper_id}|{source_id}|{target_id}|{rel_std}|{evidence}"
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
                    "relation_type": "main_effect",
                    "relation_type_std": rel_std,
                    "direction": direction,
                    "relation_form": relation_form,
                    "relation_form_raw": relation_form_raw,
                    "verification": rel.get("verification", ""),
                    "evidence_section": evidence,
                    "evidence_snippet": rel.get("evidence_snippet", ""),
                    "hypothesis_label": rel.get("hypothesis_label", ""),
                    "paper_year": paper_payload.get("publication_year"),
                    "display_effect_class": _display_effect_class(direction, relation_form),
                }
            )

        for mod in bundle.moderations:
            moderator = str(mod.get("moderator", "")).strip()
            if not moderator:
                continue
            moderator_id = _canonical_var_id(moderator)
            _ensure_node(variable_nodes, node_aliases, moderator_id, moderator, [])
            condition_text = str(mod.get("condition_text", "") or "")
            for target in mod.get("moderated_effects", []) or []:
                src = str(target.get("source", "")).strip()
                tgt = str(target.get("target", "")).strip()
                if not src or not tgt:
                    continue
                src_id = _canonical_var_id(src)
                tgt_id = _canonical_var_id(tgt)
                _ensure_node(variable_nodes, node_aliases, src_id, src, [])
                _ensure_node(variable_nodes, node_aliases, tgt_id, tgt, [])
                moderation_links.append(
                    {
                        "id": f"mod::{_slug(paper_id)}::{_slug(moderator)}::{len(moderation_links)}",
                        "paper_id": paper_id,
                        "doi": doi,
                        "moderator_var": moderator,
                        "moderator_node_id": moderator_id,
                        "moderated_relation": {
                            "source_var": src,
                            "target_var": tgt,
                            "source_node_id": src_id,
                            "target_node_id": tgt_id,
                        },
                        "direction": mod.get("direction", ""),
                        "verification": mod.get("verification", ""),
                        "hypothesis_label": mod.get("hypothesis_label", ""),
                        "condition_text": condition_text,
                        "evidence_section": mod.get("evidence_section", ""),
                        "evidence_snippet": mod.get("evidence_snippet", ""),
                        "paper_year": paper_payload.get("publication_year"),
                    }
                )

        for interaction in bundle.interactions:
            inputs = list(interaction.get("inputs", []) or [])
            output = str(interaction.get("output", "") or "").strip()
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

            moderator = str(interaction.get("moderator", "") or "").strip()
            moderator_id = _canonical_var_id(moderator) if moderator else ""
            if moderator and moderator_id:
                _ensure_node(variable_nodes, node_aliases, moderator_id, moderator, [])

            interaction_links.append(
                {
                    "id": f"int::{_slug(paper_id)}::{len(interaction_links)}",
                    "paper_id": paper_id,
                    "doi": doi,
                    "inputs": resolved_input_names,
                    "input_node_ids": resolved_input_ids,
                    "output": output,
                    "output_node_id": output_id,
                    "interaction_type": str(interaction.get("type", "") or ""),
                    "moderator": moderator,
                    "moderator_node_id": moderator_id,
                    "effect": str(interaction.get("effect", "") or ""),
                    "verification": str(interaction.get("verification", "") or ""),
                    "hypothesis_label": str(interaction.get("hypothesis_label", "") or ""),
                    "evidence_section": str(interaction.get("evidence_section", "") or ""),
                    "evidence_snippet": str(interaction.get("evidence_snippet", "") or ""),
                    "description": str(interaction.get("description", "") or ""),
                    "paper_year": paper_payload.get("publication_year"),
                }
            )
            interaction_type_text = str(interaction.get("type", "") or "").strip().lower()
            if "moderat" in interaction_type_text and moderator_id:
                for idx, src_name in enumerate(resolved_input_names):
                    src_id = resolved_input_ids[idx] if idx < len(resolved_input_ids) else ""
                    if not src_id or src_id == moderator_id:
                        continue
                    moderation_links.append(
                        {
                            "id": f"mod::from_inter::{_slug(paper_id)}::{len(moderation_links)}",
                            "paper_id": paper_id,
                            "doi": doi,
                            "moderator_var": moderator,
                            "moderator_node_id": moderator_id,
                            "moderated_relation": {
                                "source_var": src_name,
                                "target_var": output,
                                "source_node_id": src_id,
                                "target_node_id": output_id,
                            },
                            "direction": str(interaction.get("effect", "") or ""),
                            "verification": str(interaction.get("verification", "") or ""),
                            "hypothesis_label": str(interaction.get("hypothesis_label", "") or ""),
                            "condition_text": "",
                            "evidence_section": str(interaction.get("evidence_section", "") or ""),
                            "evidence_snippet": str(interaction.get("evidence_snippet", "") or ""),
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

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out_payload["meta"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
