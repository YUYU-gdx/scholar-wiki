from __future__ import annotations

from dataclasses import dataclass
import re


_SECTION_ABSTRACT = re.compile(r"\babstract\b", re.IGNORECASE)
_SECTION_REFERENCES = re.compile(r"\breferences?\b", re.IGNORECASE)
_SECTION_HYPOTHESES = re.compile(r"\bhypotheses?\b", re.IGNORECASE)
_SECTION_RESULTS = re.compile(r"\bresults?\b", re.IGNORECASE)
_SECTION_INTRO = re.compile(r"\bintroduction\b", re.IGNORECASE)
_SECTION_METHOD = re.compile(r"\b(method|methods|methodology|data|sample)\b", re.IGNORECASE)
_SECTION_DISCUSSION = re.compile(r"\b(discussion|conclusion|implications?)\b", re.IGNORECASE)
_MAIN_MODEL_LABEL = re.compile(r"\bmain[-\s]?model\b", re.IGNORECASE)
_HYPOTHESIS_LABEL = re.compile(r"\bH\d+[a-z]?\b", re.IGNORECASE)
_REGRESSION_SIGNAL = re.compile(r"\b(regression|ols|logit|probit|fixed effects?|random effects?|iv|did|rdd)\b", re.IGNORECASE)
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
    has_intro_block = bool(_SECTION_INTRO.search(text))
    has_method_block = bool(_SECTION_METHOD.search(text))
    has_discussion_block = bool(_SECTION_DISCUSSION.search(text))
    has_body_block = has_hypotheses_block or has_results_block
    has_main_model_signal = _has_main_model_signal(text)
    has_extra_body_signal = has_intro_block or has_method_block or has_discussion_block
    has_hypothesis_label = bool(_HYPOTHESIS_LABEL.search(text))
    has_regression_signal = bool(_REGRESSION_SIGNAL.search(text))
    has_table_signal = bool(_TABLE_TAG.search(text))
    has_stat_signal = bool(_STAT_SIGNAL.search(text))
    has_empirical_signal = (
        (has_table_signal and (has_stat_signal or has_results_block or has_method_block))
        or (has_stat_signal and (has_results_block or has_method_block))
        or (has_regression_signal and (has_method_block or has_results_block))
        or (has_hypothesis_label and has_results_block)
    )
    has_fulltext_structure = has_intro_block and (has_method_block or has_results_block or has_discussion_block)

    # Class B must be strictly "abstract + references only".
    if (
        has_abstract
        and has_references
        and not has_body_block
        and not has_main_model_signal
        and not has_extra_body_signal
        and not has_empirical_signal
    ):
        doc_class = "B"
    elif (
        has_fulltext_structure
        and (has_main_model_signal or has_empirical_signal)
    ) or (
        has_body_block
        and has_empirical_signal
        and (has_hypotheses_block or has_results_block)
    ):
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
