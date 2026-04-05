from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Protocol


_REQUIRED_KEYS = (
    "relations",
    "variable_level_theory_grounding",
    "relation_level_theory_grounding",
    "hypotheses",
    "citations",
)
_OPTIONAL_LIST_KEYS = ("paper_domains",)
_ABBR_PATTERN = re.compile(r"^[A-Z][A-Z0-9/&-]{1,7}$")
_FULL_WITH_ABBR_TEMPLATE = r"([A-Za-z][A-Za-z0-9\- ]{{2,80}}?)\s*\(\s*{abbr}\s*\)"
_ABBR_WITH_FULL_TEMPLATE = r"{abbr}\s*\(\s*([A-Za-z][A-Za-z0-9\- ]{{2,80}}?)\s*\)"


class LLMClient(Protocol):
    def complete(self, user_content: str, system_prompt: str | None = None) -> str: ...


@dataclass(slots=True)
class ExtractionBundle:
    relations: list[dict[str, Any]]
    variable_level_theory_grounding: list[dict[str, Any]]
    relation_level_theory_grounding: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    citations: list[dict[str, Any]]
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
    payload = json.loads(_coerce_json_payload_text(response_text))
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
    paper_domains = _coerce_string_list(payload.get("paper_domains", []))

    normalized["relations"] = [_normalize_relation_row(row) for row in normalized["relations"]]

    _validate_semantics(normalized)

    return ExtractionBundle(
        relations=normalized["relations"],
        variable_level_theory_grounding=normalized["variable_level_theory_grounding"],
        relation_level_theory_grounding=normalized["relation_level_theory_grounding"],
        hypotheses=normalized["hypotheses"],
        citations=normalized["citations"],
        paper_domains=paper_domains,
    )


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

    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


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
        if str(row.get("relation_form", "")).strip().lower() not in {"linear", "nonlinear"}:
            raise ValueError(f"relations[{i}].relation_form is invalid")
        if not str(row.get("source_canonical_var_id", "")).strip():
            raise ValueError(f"relations[{i}].source_canonical_var_id is required")
        if not str(row.get("target_canonical_var_id", "")).strip():
            raise ValueError(f"relations[{i}].target_canonical_var_id is required")
        if not isinstance(row.get("source_aliases", []), list) or not all(
            isinstance(v, str) for v in row.get("source_aliases", [])
        ):
            raise ValueError(f"relations[{i}].source_aliases must be list[str]")
        if not isinstance(row.get("target_aliases", []), list) or not all(
            isinstance(v, str) for v in row.get("target_aliases", [])
        ):
            raise ValueError(f"relations[{i}].target_aliases must be list[str]")
        source_var = str(row.get("source_var", "")).strip()
        target_var = str(row.get("target_var", "")).strip()
        unresolved_abbr = bool(row.get("unresolved_abbr", False))
        if (_looks_like_abbreviation(source_var) or _looks_like_abbreviation(target_var)) and not unresolved_abbr:
            raise ValueError(f"relations[{i}] contains abbreviation as primary name without unresolved_abbr")
        if unresolved_abbr and not str(row.get("abbr_form", "")).strip():
            raise ValueError(f"relations[{i}].abbr_form is required when unresolved_abbr=true")
        if str(row.get("relation_type_std", "")).strip() == "moderation":
            if not str(row.get("moderator_var", "")).strip():
                raise ValueError(f"relations[{i}].moderator_var is required for moderation")
            mr = row.get("moderated_relation")
            if not isinstance(mr, dict):
                raise ValueError(f"relations[{i}].moderated_relation is required for moderation")
            if not str(mr.get("source_var", "")).strip() or not str(mr.get("target_var", "")).strip():
                raise ValueError(f"relations[{i}].moderated_relation.source_var/target_var are required")

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


def _normalize_relation_row(row: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("source_var", "")).strip()
    target = str(row.get("target_var", "")).strip()
    direction = str(row.get("direction", "")).strip()

    normalized = dict(row)
    source_aliases = _coerce_string_list(row.get("source_aliases", [source]))
    target_aliases = _coerce_string_list(row.get("target_aliases", [target]))
    source_name, source_unresolved, source_abbr_form, source_name_resolved_by = _resolve_primary_name(
        source, source_aliases
    )
    target_name, target_unresolved, target_abbr_form, target_name_resolved_by = _resolve_primary_name(
        target, target_aliases
    )
    normalized["source_var"] = source_name
    normalized["target_var"] = target_name
    normalized["source_aliases"] = _coerce_string_list([source_name, source, *source_aliases, source_abbr_form])
    normalized["target_aliases"] = _coerce_string_list([target_name, target, *target_aliases, target_abbr_form])
    normalized["source_canonical_var_id"] = str(row.get("source_canonical_var_id", "")).strip() or f"var::{_slug(source_name)}"
    normalized["target_canonical_var_id"] = str(row.get("target_canonical_var_id", "")).strip() or f"var::{_slug(target_name)}"
    unresolved_abbr = source_unresolved or target_unresolved
    abbr_forms = _coerce_string_list(
        [
            source_abbr_form if source_unresolved else "",
            target_abbr_form if target_unresolved else "",
        ]
    )
    normalized["unresolved_abbr"] = unresolved_abbr
    normalized["abbr_form"] = ",".join(abbr_forms)
    if source_name_resolved_by == "postprocess" or target_name_resolved_by == "postprocess":
        normalized["name_resolution_source"] = "postprocess"
    elif unresolved_abbr:
        normalized["name_resolution_source"] = "fallback"
    else:
        normalized["name_resolution_source"] = str(row.get("name_resolution_source", "")).strip() or "prompt"

    relation_form = str(row.get("relation_form", "")).strip().lower()
    nonlinear_directions = {
        "u_shape",
        "u_shaped",
        "inverted_u",
        "j_shaped",
        "inverse_j_shaped",
        "s_shaped",
        "threshold",
        "hump_shaped",
        "n_shaped",
        "non_monotonic",
        "non_directional",
        "non_significant",
    }
    if relation_form not in {"linear", "nonlinear"}:
        relation_form = "nonlinear" if direction in nonlinear_directions else "linear"
    normalized["relation_form"] = relation_form
    normalized["nonlinear_pattern"] = str(row.get("nonlinear_pattern", "") or "").strip()
    relation_type_raw = str(row.get("relation_type", "") or "").strip()
    normalized["relation_type_raw"] = relation_type_raw
    normalized["relation_type_std"] = _normalize_relation_type(relation_type_raw)
    normalized["relation_type"] = normalized["relation_type_std"]
    normalized["moderator_var"] = str(row.get("moderator_var", "") or "").strip()
    normalized["mediator_var"] = str(row.get("mediator_var", "") or "").strip()
    normalized["condition_text"] = str(row.get("condition_text", "") or "").strip()
    mr = row.get("moderated_relation") if isinstance(row.get("moderated_relation"), dict) else {}
    normalized["moderated_relation"] = {
        "source_var": str((mr or {}).get("source_var", "") or "").strip(),
        "target_var": str((mr or {}).get("target_var", "") or "").strip(),
        "hypothesis_label": str((mr or {}).get("hypothesis_label", "") or "").strip(),
    }
    return normalized


def _resolve_primary_name(
    primary: str,
    aliases: list[str],
) -> tuple[str, bool, str, str]:
    name = str(primary or "").strip()
    alias_pool = _coerce_string_list([name, *aliases])
    if not _looks_like_abbreviation(name):
        return name, False, "", "prompt"

    abbr_re = re.escape(name)
    patterns = (
        re.compile(_FULL_WITH_ABBR_TEMPLATE.format(abbr=abbr_re), flags=re.IGNORECASE),
        re.compile(_ABBR_WITH_FULL_TEMPLATE.format(abbr=abbr_re), flags=re.IGNORECASE),
    )
    for alias in alias_pool:
        for pattern in patterns:
            m = pattern.search(alias)
            if not m:
                continue
            full_name = re.sub(r"\s+", " ", str(m.group(1) or "").strip())
            if full_name and not _looks_like_abbreviation(full_name):
                return full_name, False, name, "postprocess"
    return name, True, name, "fallback"


def _looks_like_abbreviation(text: str) -> bool:
    token = str(text or "").strip()
    if not token or " " in token:
        return False
    return bool(_ABBR_PATTERN.match(token))


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
    v = str(text or "").strip().lower()
    v = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in v)
    v = "-".join(part for part in v.split("-") if part)
    return v or "unknown"


def _complete_with_messages(llm_client: LLMClient, user_content: str, system_prompt: str) -> str:
    try:
        return llm_client.complete(user_content=user_content, system_prompt=system_prompt)
    except TypeError:
        try:
            return llm_client.complete(user_content, system_prompt)
        except TypeError:
            merged = f"{system_prompt}\n\n{user_content}".strip()
            return llm_client.complete(merged)


def _load_sibling_module(module_name: str, filename: str) -> Any:
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load sibling module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
