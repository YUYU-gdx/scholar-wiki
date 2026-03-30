from __future__ import annotations

from dataclasses import dataclass
import re


_SECTION_ABSTRACT = re.compile(r"\babstract\b", re.IGNORECASE)
_SECTION_REFERENCES = re.compile(r"\breferences?\b", re.IGNORECASE)
_SECTION_HYPOTHESES = re.compile(r"\bhypotheses?\b", re.IGNORECASE)
_SECTION_RESULTS = re.compile(r"\bresults?\b", re.IGNORECASE)
_MAIN_MODEL_LABEL = re.compile(r"\bmain[-\s]?model\b", re.IGNORECASE)
_STAT_SIGNAL = re.compile(
    r"(\b(beta|coef|coefficient|odds ratio|hazard ratio|hr|or|r)\b\s*[:=]?\s*[-+]?\d"
    r"|p\s*[<=>]\s*0?\.\d+"
    r"|[bB]\s*[:=]?\s*[-+]?\d)",
    re.IGNORECASE,
)
_TABLE_TAG = re.compile(r"<table\b", re.IGNORECASE)


@dataclass(slots=True)
class DocumentQualification:
    doc_class: str
    has_abstract: bool
    has_references: bool
    has_hypotheses_block: bool
    has_results_block: bool
    has_main_model_signal: bool

    @property
    def is_class_a(self) -> bool:
        return self.doc_class == "A"

    @property
    def is_class_b(self) -> bool:
        return self.doc_class == "B"

    @property
    def is_class_c(self) -> bool:
        return self.doc_class == "C"


def classify_document(html: str) -> DocumentQualification:
    text = _normalize_text(html)

    has_abstract = bool(_SECTION_ABSTRACT.search(text))
    has_references = bool(_SECTION_REFERENCES.search(text))
    has_hypotheses_block = bool(_SECTION_HYPOTHESES.search(text))
    has_results_block = bool(_SECTION_RESULTS.search(text))
    has_body_block = has_hypotheses_block or has_results_block
    has_main_model_signal = _has_main_model_signal(text)

    if has_abstract and has_references and not has_body_block and not has_main_model_signal:
        doc_class = "B"
    elif has_body_block and has_main_model_signal:
        doc_class = "A"
    else:
        doc_class = "C"

    return DocumentQualification(
        doc_class=doc_class,
        has_abstract=has_abstract,
        has_references=has_references,
        has_hypotheses_block=has_hypotheses_block,
        has_results_block=has_results_block,
        has_main_model_signal=has_main_model_signal,
    )


def is_class_a(document: DocumentQualification) -> bool:
    return document.doc_class == "A"


def is_class_b(document: DocumentQualification) -> bool:
    return document.doc_class == "B"


def is_class_c(document: DocumentQualification) -> bool:
    return document.doc_class == "C"


def _normalize_text(html: str) -> str:
    return re.sub(r"\s+", " ", html).strip()


def _has_main_model_signal(text: str) -> bool:
    return bool(
        _MAIN_MODEL_LABEL.search(text)
        and (_TABLE_TAG.search(text) or _STAT_SIGNAL.search(text))
    )
