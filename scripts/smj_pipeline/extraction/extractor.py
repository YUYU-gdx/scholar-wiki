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
    "main_effects",
)
_OPTIONAL_LIST_KEYS = (
    "variable_definitions",
    "direct_effects",
    "moderations",
    "interactions",
    "context_variables",
)


class LLMClient(Protocol):
    def complete(self, user_content: str, system_prompt: str | None = None) -> str: ...


@dataclass(slots=True)
class ExtractionBundle:
    extractability_status: str
    paper_type: str
    extractability_reason: str
    extractability_evidence_section: str
    main_effects: list[dict[str, Any]]
    variable_definitions: list[dict[str, Any]]
    direct_effects: list[dict[str, Any]]
    moderations: list[dict[str, Any]]
    interactions: list[dict[str, Any]]
    paper_domains: list[str]
    context_variables: list[str]
    operationalization: dict[str, Any]


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
    payload = _bridge_payload_shapes(payload)
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
        if key == "context_variables":
            continue
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{key} items must be objects")
        normalized_lists[key] = [dict(item) for item in value]
    context_variables = _coerce_string_list(payload.get("context_variables", []))
    operationalization = _normalize_operationalization(payload.get("operationalization", {}))

    if extractability_status in {"no", "uncertain"}:
        if normalized_lists["main_effects"]:
            raise ValueError("main_effects must be empty when extractability_status is no/uncertain")
        if normalized_lists["direct_effects"]:
            raise ValueError("direct_effects must be empty when extractability_status is no/uncertain")
        if normalized_lists["moderations"]:
            raise ValueError("moderations must be empty when extractability_status is no/uncertain")
        if normalized_lists["interactions"]:
            raise ValueError("interactions must be empty when extractability_status is no/uncertain")

    main_effects = [_normalize_main_effect_row(r) for r in normalized_lists["main_effects"]]
    variable_definitions = [_normalize_variable_definition_row(r) for r in normalized_lists["variable_definitions"]]
    direct_effects = [_normalize_direct_effect_row(r) for r in normalized_lists["direct_effects"]]
    if not main_effects and direct_effects:
        main_effects = [_main_effect_from_direct_effect_row(r) for r in direct_effects]
    if not direct_effects and main_effects:
        direct_effects = [_direct_effect_from_main_effect_row(r) for r in main_effects]
    moderations = [_normalize_moderation_row(r) for r in normalized_lists["moderations"]]
    interactions = [_normalize_interaction_row(r) for r in normalized_lists["interactions"]]

    _validate_main_effects(main_effects)
    _validate_variable_definitions(variable_definitions)
    _validate_direct_effects(direct_effects, schemas)
    _validate_moderations(moderations, schemas)
    _validate_interactions(interactions, schemas)

    return ExtractionBundle(
        extractability_status=extractability_status,
        paper_type=str(payload.get("paper_type", "") or "").strip(),
        extractability_reason=str(payload.get("extractability_reason", "") or "").strip(),
        extractability_evidence_section=str(payload.get("extractability_evidence_section", "") or "").strip(),
        main_effects=main_effects,
        variable_definitions=variable_definitions,
        direct_effects=direct_effects,
        moderations=moderations,
        interactions=interactions,
        paper_domains=_coerce_string_list(payload.get("paper_domains", [])),
        context_variables=context_variables,
        operationalization=operationalization,
    )


def _validate_main_effects(rows: list[dict[str, Any]]) -> None:
    for i, row in enumerate(rows):
        _require_non_empty(row, ("from", "to", "verification", "evidence_section"), f"main_effects[{i}]")


def _validate_variable_definitions(rows: list[dict[str, Any]]) -> None:
    for i, row in enumerate(rows):
        _require_non_empty(row, ("variable", "definition", "definition_evidence_section"), f"variable_definitions[{i}]")


def _validate_direct_effects(rows: list[dict[str, Any]], schemas: Any) -> None:
    allowed_dir = set(schemas.ALLOWED_EFFECT_DIRECTIONS)
    allowed_form = set(schemas.ALLOWED_RELATION_FORM)
    allowed_ver = set(schemas.ALLOWED_VERIFICATION)

    for i, row in enumerate(rows):
        _require_non_empty(row, ("source", "target", "direction", "relation_form", "verification", "evidence_section"), f"direct_effects[{i}]")
        if row["direction"] not in allowed_dir:
            raise ValueError(f"direct_effects[{i}].direction is invalid")
        if row["relation_form"] not in allowed_form:
            raise ValueError(f"direct_effects[{i}].relation_form is invalid")
        if row["verification"] not in allowed_ver:
            raise ValueError(f"direct_effects[{i}].verification is invalid")


def _validate_moderations(rows: list[dict[str, Any]], schemas: Any) -> None:
    allowed_dir = set(schemas.ALLOWED_MODERATION_DIRECTIONS)
    allowed_ver = set(schemas.ALLOWED_VERIFICATION)

    for i, row in enumerate(rows):
        _require_non_empty(row, ("moderator", "direction", "verification", "evidence_section"), f"moderations[{i}]")
        if row["direction"] not in allowed_dir:
            raise ValueError(f"moderations[{i}].direction is invalid")
        if row["verification"] not in allowed_ver:
            raise ValueError(f"moderations[{i}].verification is invalid")
        targets = row.get("moderated_effects", [])
        if not isinstance(targets, list) or not targets:
            raise ValueError(f"moderations[{i}].moderated_effects must be non-empty list")
        for j, t in enumerate(targets):
            if not isinstance(t, dict):
                raise ValueError(f"moderations[{i}].moderated_effects[{j}] must be object")
            _require_non_empty(t, ("source", "target"), f"moderations[{i}].moderated_effects[{j}]")


def _validate_interactions(rows: list[dict[str, Any]], schemas: Any) -> None:
    allowed_ver = set(schemas.ALLOWED_VERIFICATION)
    allowed_effect = set(schemas.ALLOWED_INTERACTION_EFFECT).union({"+", "-", "conditional"})

    for i, row in enumerate(rows):
        _require_non_empty(row, ("output", "verification", "evidence_section"), f"interactions[{i}]")
        if row["verification"] not in allowed_ver:
            raise ValueError(f"interactions[{i}].verification is invalid")
        effect = str(row.get("effect", "") or "").strip().lower()
        if effect and effect not in allowed_effect:
            raise ValueError(f"interactions[{i}].effect is invalid")
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


def _normalize_variable_definition_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "variable": str(row.get("variable", "") or "").strip(),
        "aliases": [],
        "definition": str(row.get("definition", "") or "").strip(),
        "definition_evidence_section": str(row.get("definition_evidence_section", "") or "").strip(),
    }


def _normalize_main_effect_row(row: dict[str, Any]) -> dict[str, Any]:
    effect_raw = str(row.get("effect", "") or "").strip()
    return {
        "from": str(row.get("from", "") or "").strip(),
        "to": str(row.get("to", "") or "").strip(),
        "effect": effect_raw,
        "hypothesis_label": str(row.get("hypothesis_label", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
        "evidence_section": str(row.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(row.get("evidence_snippet", "") or "").strip(),
        "description": str(row.get("description", "") or "").strip(),
    }


def _normalize_direct_effect_row(row: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("source", "") or "").strip()
    target = str(row.get("target", "") or "").strip()
    return {
        "source": source,
        "target": target,
        "source_aliases": [],
        "target_aliases": [],
        "direction": str(row.get("direction", "") or "").strip().lower(),
        "relation_form": str(row.get("relation_form", "") or "").strip().lower(),
        "relation_form_raw": str(row.get("relation_form_raw", "") or "").strip(),
        "hypothesis_label": str(row.get("hypothesis_label", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
        "evidence_section": str(row.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(row.get("evidence_snippet", "") or "").strip(),
        "source_canonical_var_id": _canonical_var_id(source),
        "target_canonical_var_id": _canonical_var_id(target),
    }


def _normalize_moderation_row(row: dict[str, Any]) -> dict[str, Any]:
    moderator = str(row.get("moderator", "") or "").strip()
    targets: list[dict[str, str]] = []
    raw_targets = row.get("moderated_effects", [])
    if isinstance(raw_targets, list):
        for t in raw_targets:
            if not isinstance(t, dict):
                continue
            targets.append(
                {
                    "source": str(t.get("source", "") or "").strip(),
                    "target": str(t.get("target", "") or "").strip(),
                    "source_canonical_var_id": str(t.get("source_canonical_var_id", "") or "").strip(),
                    "target_canonical_var_id": str(t.get("target_canonical_var_id", "") or "").strip(),
                }
            )

    for t in targets:
        source = str(t.get("source", "") or "").strip()
        target = str(t.get("target", "") or "").strip()
        if source and not str(t.get("source_canonical_var_id", "") or "").strip():
            t["source_canonical_var_id"] = _canonical_var_id(source)
        if target and not str(t.get("target_canonical_var_id", "") or "").strip():
            t["target_canonical_var_id"] = _canonical_var_id(target)

    return {
        "moderator": moderator,
        "moderator_aliases": [],
        "moderated_effects": targets,
        "direction": str(row.get("direction", "") or "").strip().lower(),
        "hypothesis_label": str(row.get("hypothesis_label", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
        "evidence_section": str(row.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(row.get("evidence_snippet", "") or "").strip(),
        "condition_text": str(row.get("condition_text", "") or "").strip(),
        "moderator_canonical_var_id": _canonical_var_id(moderator),
    }


def _normalize_interaction_row(row: dict[str, Any]) -> dict[str, Any]:
    output = str(row.get("output", "") or "").strip()
    inputs_raw = row.get("inputs", [])
    inputs = _coerce_string_list(inputs_raw if isinstance(inputs_raw, list) else [inputs_raw])
    moderator = str(row.get("moderator", "") or "").strip()
    result = {
        "inputs": inputs,
        "output": output,
        "type": str(row.get("type", "") or "").strip(),
        "moderator": moderator,
        "effect": str(row.get("effect", "") or "").strip().lower() if str(row.get("effect", "") or "").strip().isalpha() else str(row.get("effect", "") or "").strip(),
        "hypothesis_label": str(row.get("hypothesis_label", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
        "evidence_section": str(row.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(row.get("evidence_snippet", "") or "").strip(),
        "description": str(row.get("description", "") or "").strip(),
        "input_canonical_var_ids": [_canonical_var_id(v) for v in inputs],
        "output_canonical_var_id": _canonical_var_id(output),
        "moderator_canonical_var_id": _canonical_var_id(moderator),
    }
    return result


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
            '"main_effects"',
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
    except Exception as exc:  # pragma: no cover
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


def _bridge_payload_shapes(payload: dict[str, Any]) -> dict[str, Any]:
    p = dict(payload)
    if "main_effects" not in p and isinstance(p.get("direct_effects"), list):
        converted: list[dict[str, Any]] = []
        for item in p.get("direct_effects", []):
            if not isinstance(item, dict):
                continue
            converted.append(
                {
                    "from": str(item.get("source", "") or "").strip(),
                    "to": str(item.get("target", "") or "").strip(),
                    "effect": _main_effect_from_direct_effect_row(item).get("effect", ""),
                    "hypothesis_label": str(item.get("hypothesis_label", "") or "").strip(),
                    "verification": str(item.get("verification", "") or "").strip(),
                    "evidence_section": str(item.get("evidence_section", "") or "").strip(),
                    "evidence_snippet": str(item.get("evidence_snippet", "") or "").strip(),
                    "description": "",
                }
            )
        p["main_effects"] = converted
    p.setdefault("direct_effects", [])
    p.setdefault("variable_definitions", [])
    p.setdefault("moderations", [])
    p.setdefault("interactions", [])
    p.setdefault("context_variables", [])
    p.setdefault("operationalization", {})
    return p


def _normalize_operationalization(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in value.items():
        key = str(k or "").strip()
        if not key:
            continue
        if isinstance(v, dict):
            out[key] = {str(kk or "").strip(): vv for kk, vv in v.items() if str(kk or "").strip()}
        elif isinstance(v, list):
            out[key] = {"operationalized_as": _coerce_string_list(v)}
        elif isinstance(v, str):
            out[key] = {"operationalized_as": [v.strip()]} if v.strip() else {}
        else:
            out[key] = {}
    return out


def _main_effect_from_direct_effect_row(row: dict[str, Any]) -> dict[str, Any]:
    direction = str(row.get("direction", "") or "").strip().lower()
    relation_form = str(row.get("relation_form", "") or "").strip().lower()
    if relation_form == "nonlinear" or direction == "nonlinear":
        effect = "nonlinear"
    elif direction == "positive":
        effect = "+"
    elif direction == "negative":
        effect = "-"
    elif direction:
        effect = direction
    else:
        effect = ""
    return {
        "from": str(row.get("source", "") or "").strip(),
        "to": str(row.get("target", "") or "").strip(),
        "effect": effect,
        "hypothesis_label": str(row.get("hypothesis_label", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
        "evidence_section": str(row.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(row.get("evidence_snippet", "") or "").strip(),
        "description": "",
    }


def _direct_effect_from_main_effect_row(row: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("from", "") or "").strip()
    target = str(row.get("to", "") or "").strip()
    effect = str(row.get("effect", "") or "").strip().lower()
    direction = "unclear"
    relation_form = "linear"
    relation_form_raw = ""
    if effect in {"+", "positive"}:
        direction = "positive"
    elif effect in {"-", "negative"}:
        direction = "negative"
    elif "nonlinear" in effect or "u" in effect:
        direction = "nonlinear"
        relation_form = "nonlinear"
        relation_form_raw = str(row.get("effect", "") or "").strip()
    elif effect in {"mixed", "unclear"}:
        direction = effect
    return {
        "source": source,
        "target": target,
        "source_aliases": [],
        "target_aliases": [],
        "direction": direction,
        "relation_form": relation_form,
        "relation_form_raw": relation_form_raw,
        "hypothesis_label": str(row.get("hypothesis_label", "") or "").strip(),
        "verification": str(row.get("verification", "") or "").strip().lower(),
        "evidence_section": str(row.get("evidence_section", "") or "").strip(),
        "evidence_snippet": str(row.get("evidence_snippet", "") or "").strip(),
        "source_canonical_var_id": _canonical_var_id(source),
        "target_canonical_var_id": _canonical_var_id(target),
    }


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
