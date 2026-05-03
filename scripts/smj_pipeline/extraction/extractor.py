from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Protocol


_REQUIRED_SCALAR_KEYS = (
    "extractability_status",
    "paper_type",
    "extractability_reason",
    "extractability_evidence_section",
)
_REQUIRED_LIST_KEYS = (
    "direct_effects",
)
_OPTIONAL_LIST_KEYS = (
    "variable_definitions",
    "moderations",
    "interactions",
)


class LLMClient(Protocol):
    def complete(self, user_content: str, system_prompt: str | None = None) -> str: ...


@dataclass(slots=True)
class ExtractionBundle:
    extractability_status: str
    paper_type: str
    extractability_reason: str
    extractability_evidence_section: str
    direct_effects: list[dict[str, Any]]
    variable_definitions: list[dict[str, Any]]
    moderations: list[dict[str, Any]]
    interactions: list[dict[str, Any]]
    paper_domains: list[str]


def extract_records(document_html: str, llm_client: LLMClient) -> ExtractionBundle:
    bundle, _ = extract_records_with_raw(document_html, llm_client)
    return bundle


def extract_records_with_raw(document_html: str, llm_client: LLMClient) -> tuple[ExtractionBundle, str]:
    prompts_module = _load_sibling_module("smj_pipeline_extraction_prompts", "prompts.py")
    system_prompt, user_content = prompts_module.build_extraction_messages(document_html)
    response_text = _complete_with_messages(llm_client, user_content=user_content, system_prompt=system_prompt)
    bundle = parse_extraction_response(response_text)
    html_domains = list(getattr(prompts_module, "extract_domain_tags_from_html")(document_html))
    if html_domains:
        bundle.paper_domains = html_domains
    return bundle, response_text


def parse_extraction_response(response_text: str) -> ExtractionBundle:
    payload = _parse_payload(response_text)
    if not isinstance(payload, dict):
        raise ValueError("extraction response must be a JSON/YAML object")

    missing_scalar = [k for k in _REQUIRED_SCALAR_KEYS if k not in payload]
    missing_list = [k for k in _REQUIRED_LIST_KEYS if k not in payload]
    missing_keys = missing_scalar + missing_list
    if missing_keys:
        raise ValueError(f"missing extraction keys: {', '.join(missing_keys)}")

    schemas = _load_sibling_module("smj_pipeline_extraction_schemas_for_extractor", "schemas.py")

    extractability_status = _normalize_extractability_status(payload.get("extractability_status", ""))
    if extractability_status not in set(schemas.ALLOWED_EXTRACTABILITY_STATUS):
        raise ValueError("extractability_status is invalid")

    normalized_lists: dict[str, list[dict[str, Any]]] = {}
    for key in (*_REQUIRED_LIST_KEYS, *_OPTIONAL_LIST_KEYS):
        value = payload.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{key} items must be objects")
        normalized_lists[key] = [dict(item) for item in value]

    if extractability_status in {"no", "uncertain"}:
        if normalized_lists["direct_effects"]:
            raise ValueError("direct_effects must be empty when extractability_status is no/uncertain")
        if normalized_lists["moderations"]:
            raise ValueError("moderations must be empty when extractability_status is no/uncertain")
        if normalized_lists["interactions"]:
            raise ValueError("interactions must be empty when extractability_status is no/uncertain")

    direct_effects = [_normalize_direct_effect_row(r) for r in normalized_lists["direct_effects"]]
    variable_definitions = [_normalize_variable_definition_row(r) for r in normalized_lists["variable_definitions"]]
    moderations = [_normalize_moderation_row(r) for r in normalized_lists["moderations"]]
    interactions = [_normalize_interaction_row(r) for r in normalized_lists["interactions"]]

    _validate_direct_effects(direct_effects, schemas)
    _validate_variable_definitions(variable_definitions)
    _validate_moderations(moderations, schemas)
    _validate_interactions(interactions, schemas)

    return ExtractionBundle(
        extractability_status=extractability_status,
        paper_type=str(payload.get("paper_type", "") or "").strip(),
        extractability_reason=str(payload.get("extractability_reason", "") or "").strip(),
        extractability_evidence_section=str(payload.get("extractability_evidence_section", "") or "").strip(),
        direct_effects=direct_effects,
        variable_definitions=variable_definitions,
        moderations=moderations,
        interactions=interactions,
        paper_domains=_coerce_string_list(payload.get("paper_domains", [])),
    )


def _validate_direct_effects(rows: list[dict[str, Any]], schemas: Any) -> None:
    allowed_form = set(schemas.ALLOWED_EFFECT_FORM)
    allowed_ver = set(schemas.ALLOWED_VERIFICATION)

    for i, row in enumerate(rows):
        _require_non_empty(row, ("source", "target", "effect_form", "verification", "evidence_text"), f"direct_effects[{i}]")
        if row["effect_form"] not in allowed_form:
            raise ValueError(f"direct_effects[{i}].effect_form is invalid")
        if row["verification"] not in allowed_ver:
            raise ValueError(f"direct_effects[{i}].verification is invalid")


def _validate_variable_definitions(rows: list[dict[str, Any]]) -> None:
    for i, row in enumerate(rows):
        _require_non_empty(row, ("variable_name", "definition"), f"variable_definitions[{i}]")


def _validate_moderations(rows: list[dict[str, Any]], schemas: Any) -> None:
    allowed_form = set(schemas.ALLOWED_EFFECT_FORM)
    allowed_ver = set(schemas.ALLOWED_VERIFICATION)

    for i, row in enumerate(rows):
        _require_non_empty(row, ("moderator", "source", "target", "effect_form", "verification", "evidence_text"), f"moderations[{i}]")
        if row["effect_form"] not in allowed_form:
            raise ValueError(f"moderations[{i}].effect_form is invalid")
        if row["verification"] not in allowed_ver:
            raise ValueError(f"moderations[{i}].verification is invalid")


def _validate_interactions(rows: list[dict[str, Any]], schemas: Any) -> None:
    allowed_form = set(schemas.ALLOWED_EFFECT_FORM)
    allowed_ver = set(schemas.ALLOWED_VERIFICATION)

    for i, row in enumerate(rows):
        _require_non_empty(row, ("output", "effect_form", "verification", "evidence_text"), f"interactions[{i}]")
        if row["effect_form"] not in allowed_form:
            raise ValueError(f"interactions[{i}].effect_form is invalid")
        if row["verification"] not in allowed_ver:
            raise ValueError(f"interactions[{i}].verification is invalid")
        inputs = row.get("inputs", [])
        if not isinstance(inputs, list) or len(inputs) < 2:
            raise ValueError(f"interactions[{i}].inputs must contain at least 2 variables")
        for j, v in enumerate(inputs):
            if not str(v or "").strip():
                raise ValueError(f"interactions[{i}].inputs[{j}] is required")


def _require_non_empty(row: dict[str, Any], fields: tuple[str, ...], row_name: str) -> None:
    for field in fields:
        if not str(row.get(field, "")).strip():
            raise ValueError(f"{row_name}.{field} is required")


def _normalize_direct_effect_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(row.get("source", "") or "").strip(),
        "target": str(row.get("target", "") or "").strip(),
        "effect_form": str(row.get("effect_form", "") or "").strip().lower(),
        "theory_name": str(row.get("theory_name", "") or "").strip(),
        "evidence_text": str(row.get("evidence_text", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
    }


def _normalize_moderation_row(row: dict[str, Any]) -> dict[str, Any]:
    moderator = str(row.get("moderator", "") or "").strip()
    return {
        "moderator": moderator,
        "source": str(row.get("source", "") or "").strip(),
        "target": str(row.get("target", "") or "").strip(),
        "moderator_aliases": _coerce_string_list(row.get("moderator_aliases", [])),
        "effect_form": str(row.get("effect_form", "") or "").strip().lower(),
        "theory_name": str(row.get("theory_name", "") or "").strip(),
        "evidence_text": str(row.get("evidence_text", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
    }


def _normalize_interaction_row(row: dict[str, Any]) -> dict[str, Any]:
    output = str(row.get("output", "") or "").strip()
    inputs_raw = row.get("inputs", [])
    inputs = _coerce_string_list(inputs_raw if isinstance(inputs_raw, list) else [inputs_raw])
    return {
        "inputs": inputs,
        "output": output,
        "effect_form": str(row.get("effect_form", "") or "").strip().lower(),
        "theory_name": str(row.get("theory_name", "") or "").strip(),
        "evidence_text": str(row.get("evidence_text", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
    }


def _normalize_variable_definition_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "variable_name": str(row.get("variable_name", "") or "").strip(),
        "definition": str(row.get("definition", "") or "").strip(),
        "measurement": str(row.get("measurement", "") or "").strip(),
        "aliases": _coerce_string_list(row.get("aliases", [])),
    }


def _coerce_json_payload_text(response_text: str) -> str:
    text = str(response_text or "").strip()
    if not text:
        return text

    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return text


def _parse_payload(response_text: str) -> dict[str, Any]:
    text = _coerce_json_payload_text(response_text)
    try:
        payload = json.loads(text)
    except Exception:
        payload = _try_parse_embedded_json(text)
        if payload is None:
            payload = _parse_yaml_payload(text)
    if not isinstance(payload, dict):
        raise ValueError("extraction response must be object")
    return payload


def _try_parse_embedded_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    marker_hit = any(
        marker in snippet
        for marker in (
            '"extractability_status"',
            '"direct_effects"',
        )
    )
    if not marker_hit:
        return None
    try:
        obj = json.loads(snippet)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _parse_yaml_payload(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:
        raise ValueError(f"yaml parse unavailable: {exc}") from exc
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("yaml payload must be object")
    return payload


def _normalize_extractability_status(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "y"}:
        return "yes"
    if text in {"false", "no", "n"}:
        return "no"
    return text


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        seq = [value]
    elif isinstance(value, list):
        seq = value
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in seq:
        txt = str(item or "").strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def _slug(text: str) -> str:
    value = " ".join(str(text or "").strip().lower().split())
    value = "".join(ch if ch.isalnum() else "-" for ch in value)
    while "--" in value:
        value = value.replace("--", "-")
    return value.strip("-") or "unknown"


def _canonical_var_id(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    return f"var::{value}" if value else "var::unknown"


def _load_sibling_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _complete_with_messages(llm_client: LLMClient, user_content: str, system_prompt: str) -> str:
    return llm_client.complete(user_content=user_content, system_prompt=system_prompt)
