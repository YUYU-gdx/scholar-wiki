from __future__ import annotations

from dataclasses import dataclass


ALLOWED_DIRECTIONS = {
    "positive",
    "negative",
    "u_shaped",
    "u_shape",
    "inverted_u",
    "non_directional",
    "non_significant",
}

ALLOWED_VERIFICATION = {
    "supported",
    "partially_supported",
    "not_supported",
}


@dataclass(slots=True)
class ExtractionSchema:
    model_tag: str
    direction: str
    verification: str
    evidence_anchor: str

    def __post_init__(self) -> None:
        if self.model_tag != "main_model":
            raise ValueError("model_tag must be 'main_model'")
        if self.direction not in ALLOWED_DIRECTIONS:
            raise ValueError(f"invalid direction: {self.direction}")
        if self.verification not in ALLOWED_VERIFICATION:
            raise ValueError(f"invalid verification: {self.verification}")
        if not self.evidence_anchor or not self.evidence_anchor.strip():
            raise ValueError("evidence_anchor is required")
