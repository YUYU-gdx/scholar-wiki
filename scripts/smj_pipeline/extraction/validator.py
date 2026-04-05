from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any


@dataclass(slots=True)
class RejectedRecord:
    record: dict[str, Any]
    reason_codes: list[str]


@dataclass(slots=True)
class ValidationResult:
    accepted_records: list[dict[str, Any]]
    rejected_records: list[RejectedRecord]


_ABBR_PATTERN = re.compile(r"^[A-Z][A-Z0-9/&-]{1,7}$")


def validate_relation_records(records: list[dict[str, Any]]) -> ValidationResult:
    schemas_module = _load_sibling_module("smj_pipeline_extraction_schemas", "schemas.py")
    accepted_records: list[dict[str, Any]] = []
    rejected_records: list[RejectedRecord] = []

    for record in records:
        reason_codes = _collect_reason_codes(record, schemas_module)
        if reason_codes:
            rejected_records.append(
                RejectedRecord(record=_normalize_record(record), reason_codes=reason_codes)
            )
            continue
        accepted_records.append(_normalize_record(record))

    return ValidationResult(
        accepted_records=accepted_records,
        rejected_records=rejected_records,
    )


def _collect_reason_codes(record: dict[str, Any], schemas_module: Any) -> list[str]:
    reason_codes: list[str] = []

    evidence_anchor = str(record.get("evidence_anchor", ""))
    if not evidence_anchor.strip():
        reason_codes.append("MISSING_EVIDENCE_ANCHOR")

    if record.get("model_tag") != "main_model":
        reason_codes.append("INVALID_MODEL_TAG")

    if record.get("direction") not in schemas_module.ALLOWED_DIRECTIONS:
        reason_codes.append("INVALID_DIRECTION")

    if record.get("verification") not in schemas_module.ALLOWED_VERIFICATION:
        reason_codes.append("INVALID_VERIFICATION")

    source_var = str(record.get("source_var", "")).strip()
    target_var = str(record.get("target_var", "")).strip()
    unresolved_abbr = bool(record.get("unresolved_abbr", False))
    if (_looks_like_abbreviation(source_var) or _looks_like_abbreviation(target_var)) and not unresolved_abbr:
        reason_codes.append("ABBR_AS_PRIMARY_NAME")
    if unresolved_abbr and not str(record.get("abbr_form", "")).strip():
        reason_codes.append("MISSING_ABBR_FORM")

    if str(record.get("relation_type_std", "")).strip() == "moderation":
        if not str(record.get("moderator_var", "")).strip():
            reason_codes.append("MISSING_MODERATOR_VAR")
        moderated = record.get("moderated_relation")
        if not isinstance(moderated, dict):
            reason_codes.append("MISSING_MODERATED_RELATION_REF")
        else:
            if not str(moderated.get("source_var", "")).strip() or not str(moderated.get("target_var", "")).strip():
                reason_codes.append("MISSING_MODERATED_RELATION_REF")

    return reason_codes


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    return dict(sorted(record.items()))


def _looks_like_abbreviation(text: str) -> bool:
    token = str(text or "").strip()
    if not token or " " in token:
        return False
    return bool(_ABBR_PATTERN.match(token))


def _load_sibling_module(module_name: str, filename: str) -> Any:
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load sibling module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
