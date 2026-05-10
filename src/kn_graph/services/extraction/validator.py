from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
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


def validate_relation_records(records: list[dict[str, Any]]) -> ValidationResult:
    schemas_module = _load_sibling_module("smj_pipeline_extraction_schemas", "schemas.py")
    accepted_records: list[dict[str, Any]] = []
    rejected_records: list[RejectedRecord] = []

    for record in records:
        reason_codes = _collect_reason_codes(record, schemas_module)
        if reason_codes:
            rejected_records.append(RejectedRecord(record=_normalize_record(record), reason_codes=reason_codes))
            continue
        accepted_records.append(_normalize_record(record))

    return ValidationResult(accepted_records=accepted_records, rejected_records=rejected_records)


def _collect_reason_codes(record: dict[str, Any], schemas_module: Any) -> list[str]:
    reason_codes: list[str] = []

    if not str(record.get("source", "")).strip() or not str(record.get("target", "")).strip():
        reason_codes.append("MISSING_SOURCE_TARGET")

    if not str(record.get("evidence_text", "")).strip():
        reason_codes.append("MISSING_EVIDENCE_TEXT")

    effect_form = str(record.get("effect_form", "")).strip().lower()
    if effect_form not in set(schemas_module.ALLOWED_EFFECT_FORM):
        reason_codes.append("INVALID_EFFECT_FORM")

    verification = str(record.get("verification", "")).strip().lower()
    if verification not in set(schemas_module.ALLOWED_VERIFICATION):
        reason_codes.append("INVALID_VERIFICATION")

    return reason_codes


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    return dict(sorted(record.items()))


def _load_sibling_module(module_name: str, filename: str) -> Any:
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load sibling module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
