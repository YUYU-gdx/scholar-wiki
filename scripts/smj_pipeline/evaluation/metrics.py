from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MetricsResult:
    relation_coverage: float
    field_completeness: float
    hypothesis_verification_accuracy: float
    theory_traceability: float
    citation_locatability: float


def calculate_metrics(stats: dict[str, int]) -> MetricsResult:
    eligible_docs = int(stats.get("eligible_docs", 0))
    extracted_relations = int(stats.get("extracted_relations", 0))
    complete_relations = int(stats.get("complete_relations", 0))
    hypotheses_total = int(stats.get("hypotheses_total", 0))
    hypotheses_correct = int(stats.get("hypotheses_correct", 0))
    relations_with_theory = int(stats.get("relations_with_theory", 0))
    citations_total = int(stats.get("citations_total", 0))
    citations_locatable = int(stats.get("citations_locatable", 0))

    return MetricsResult(
        relation_coverage=_ratio(extracted_relations, eligible_docs),
        field_completeness=_ratio(complete_relations, extracted_relations),
        hypothesis_verification_accuracy=_ratio(hypotheses_correct, hypotheses_total),
        theory_traceability=_ratio(relations_with_theory, extracted_relations),
        citation_locatability=_ratio(citations_locatable, citations_total),
    )


def render_report(metrics: MetricsResult, context: dict[str, str | int]) -> str:
    template = _load_template()
    return template.format(
        run_id=context.get("run_id", ""),
        sample_size=context.get("sample_size", ""),
        relation_coverage=_pct(metrics.relation_coverage),
        field_completeness=_pct(metrics.field_completeness),
        hypothesis_verification_accuracy=_pct(metrics.hypothesis_verification_accuracy),
        theory_traceability=_pct(metrics.theory_traceability),
        citation_locatability=_pct(metrics.citation_locatability),
    )


def _load_template() -> str:
    path = Path(__file__).resolve().parent / "report_template.md"
    return path.read_text(encoding="utf-8")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"
