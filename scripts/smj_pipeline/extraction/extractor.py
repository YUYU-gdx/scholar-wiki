from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
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

    return ExtractionBundle(
        relations=normalized["relations"],
        variable_level_theory_grounding=normalized["variable_level_theory_grounding"],
        relation_level_theory_grounding=normalized["relation_level_theory_grounding"],
        hypotheses=normalized["hypotheses"],
        citations=normalized["citations"],
    )


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
    spec.loader.exec_module(module)
    return module
