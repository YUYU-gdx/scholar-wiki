from __future__ import annotations

from dataclasses import dataclass


ALLOWED_EXTRACTABILITY_STATUS = {"yes", "no", "uncertain"}

ALLOWED_EFFECT_DIRECTIONS = {
    "positive",
    "negative",
    "mixed",
    "unclear",
    "nonlinear",
}

ALLOWED_MODERATION_DIRECTIONS = {
    "positive",
    "negative",
    "mixed",
    "unclear",
}

ALLOWED_INTERACTION_EFFECT = {
    "positive",
    "negative",
    "mixed",
    "unclear",
    "nonlinear",
}

ALLOWED_RELATION_FORM = {
    "linear",
    "nonlinear",
    "other",
}

ALLOWED_VERIFICATION = {
    "supported",
    "not_supported",
    "mixed",
    "unclear",
}

ALLOWED_NON_REG_RELATION_TYPE = {
    "mechanism",
    "proposition",
    "qualitative_association",
    "other",
}


@dataclass(slots=True)
class DirectEffectSchema:
    source: str
    target: str
    direction: str
    relation_form: str
    verification: str
    evidence_section: str

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.target.strip():
            raise ValueError("source and target are required")
        if self.direction not in ALLOWED_EFFECT_DIRECTIONS:
            raise ValueError(f"invalid direction: {self.direction}")
        if self.relation_form not in ALLOWED_RELATION_FORM:
            raise ValueError(f"invalid relation_form: {self.relation_form}")
        if self.verification not in ALLOWED_VERIFICATION:
            raise ValueError(f"invalid verification: {self.verification}")
        if not self.evidence_section.strip():
            raise ValueError("evidence_section is required")
