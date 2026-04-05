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


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                yield payload


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
    papers: list[dict[str, Any]] = []

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
            variable_nodes.setdefault(
                source_id,
                {"id": source_id, "type": "variable", "label": source, "name": source},
            )
            variable_nodes.setdefault(
                target_id,
                {"id": target_id, "type": "variable", "label": target, "name": target},
            )

            edge_id = f"edge::{_slug(paper_id)}::{_slug(source)}::{_slug(target)}::{len(edges)}"
            edges.append(
                {
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "paper_id": paper_id,
                    "doi": doi,
                    "relation_type": rel.get("relation_type", ""),
                    "relation_form": rel.get("relation_form", "linear"),
                    "direction": rel.get("direction", ""),
                    "display_effect_class": _display_effect_class(
                        str(rel.get("direction", "")),
                        str(rel.get("relation_form", "linear")),
                    ),
                    "verification": rel.get("verification", ""),
                    "strength": _strength_from_verification(str(rel.get("verification", ""))),
                    "evidence_anchor": rel.get("evidence_anchor", ""),
                }
            )

    artifact = {
        "meta": {
            "total_rows": total,
            "success_rows": success,
            "failed_rows": failed,
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
