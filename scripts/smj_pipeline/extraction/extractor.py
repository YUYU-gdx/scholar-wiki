from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Protocol, Sequence


_REQUIRED_KEYS = (
    "relations",
    "variable_level_theory_grounding",
    "relation_level_theory_grounding",
    "hypotheses",
    "citations",
)


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


@dataclass(slots=True)
class ExtractionBundle:
    relations: list[dict[str, Any]]
    variable_level_theory_grounding: list[dict[str, Any]]
    relation_level_theory_grounding: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    citations: list[dict[str, Any]]


def extract_records(evidence_spans: Sequence[object], llm_client: LLMClient) -> ExtractionBundle:
    evidence_json = json.dumps(_serialize_spans(evidence_spans), indent=2, ensure_ascii=True)
    prompt = _build_prompt(evidence_json)
    response_text = llm_client.complete(prompt)
    return parse_extraction_response(response_text)


def parse_extraction_response(response_text: str) -> ExtractionBundle:
    payload = json.loads(response_text)
    if not isinstance(payload, dict):
        raise ValueError("extraction response must be a JSON object")

    missing_keys = [key for key in _REQUIRED_KEYS if key not in payload]
    if missing_keys:
        raise ValueError(f"missing extraction keys: {', '.join(missing_keys)}")

    normalized: dict[str, list[dict[str, Any]]] = {}
    for key in _REQUIRED_KEYS:
        value = payload[key]
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{key} items must be objects")
        normalized[key] = value

    _validate_semantics(normalized)

    return ExtractionBundle(
        relations=normalized["relations"],
        variable_level_theory_grounding=normalized["variable_level_theory_grounding"],
        relation_level_theory_grounding=normalized["relation_level_theory_grounding"],
        hypotheses=normalized["hypotheses"],
        citations=normalized["citations"],
    )


def _validate_semantics(payload: dict[str, list[dict[str, Any]]]) -> None:
    schemas_module = _load_sibling_module("smj_pipeline_extraction_schemas_for_extractor", "schemas.py")
    allowed_direction = set(schemas_module.ALLOWED_DIRECTIONS)
    allowed_verification = set(schemas_module.ALLOWED_VERIFICATION)

    for i, row in enumerate(payload["relations"]):
        _require_non_empty(row, ("source_var", "target_var", "relation_type", "model_tag", "direction", "verification", "evidence_anchor"), f"relations[{i}]")
        if row["model_tag"] != "main_model":
            raise ValueError(f"relations[{i}].model_tag must be 'main_model'")
        if row["direction"] not in allowed_direction:
            raise ValueError(f"relations[{i}].direction is invalid")
        if row["verification"] not in allowed_verification:
            raise ValueError(f"relations[{i}].verification is invalid")

    for i, row in enumerate(payload["variable_level_theory_grounding"]):
        _require_non_empty(row, ("variable", "theory", "evidence_anchor"), f"variable_level_theory_grounding[{i}]")

    for i, row in enumerate(payload["relation_level_theory_grounding"]):
        _require_non_empty(row, ("source_var", "target_var", "theory", "evidence_anchor"), f"relation_level_theory_grounding[{i}]")

    for i, row in enumerate(payload["hypotheses"]):
        _require_non_empty(row, ("label", "statement", "verification", "evidence_anchor"), f"hypotheses[{i}]")
        if row["verification"] not in allowed_verification:
            raise ValueError(f"hypotheses[{i}].verification is invalid")

    allowed_sections = {"background", "hypothesis", "discussion"}
    for i, row in enumerate(payload["citations"]):
        _require_non_empty(row, ("source_text", "citation_key", "evidence_anchor"), f"citations[{i}]")
        section = str(row.get("section_tag", "")).strip().lower()
        if section and section not in allowed_sections:
            raise ValueError(f"citations[{i}].section_tag is invalid")


def _require_non_empty(row: dict[str, Any], fields: tuple[str, ...], row_name: str) -> None:
    for field in fields:
        if not str(row.get(field, "")).strip():
            raise ValueError(f"{row_name}.{field} is required")


def _serialize_spans(evidence_spans: Sequence[object]) -> list[dict[str, Any]]:
    return [
        {
            "kind": getattr(span, "kind"),
            "text": getattr(span, "text"),
            "start": getattr(span, "start"),
            "end": getattr(span, "end"),
            "section_title": getattr(span, "section_title", None),
        }
        for span in evidence_spans
    ]


def _build_prompt(evidence_json: str) -> str:
    prompts_module = _load_sibling_module("smj_pipeline_extraction_prompts", "prompts.py")
    return prompts_module.build_extraction_prompt(evidence_json)


def _load_sibling_module(module_name: str, filename: str) -> Any:
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load sibling module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
