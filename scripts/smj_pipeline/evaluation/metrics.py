from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MetricsResult:
    extractable_rate: float
    mean_direct_effects_per_doc: float
    mean_moderations_per_doc: float
    direct_effect_validation_rate: float


def calculate_metrics(stats: dict[str, int]) -> MetricsResult:
    eligible_docs = int(stats.get("eligible_docs", 0))
    extractable_yes_docs = int(stats.get("extractable_yes_docs", 0))
    direct_effects_total = int(stats.get("direct_effects_total", 0))
    moderations_total = int(stats.get("moderations_total", 0))
    validated_direct_effects = int(stats.get("validated_direct_effects", 0))

    return MetricsResult(
        extractable_rate=_ratio(extractable_yes_docs, eligible_docs),
        mean_direct_effects_per_doc=_ratio(direct_effects_total, eligible_docs),
        mean_moderations_per_doc=_ratio(moderations_total, eligible_docs),
        direct_effect_validation_rate=_ratio(validated_direct_effects, direct_effects_total),
    )


def render_report(metrics: MetricsResult, context: dict[str, str | int]) -> str:
    template = _load_template()
    return template.format(
        run_id=context.get("run_id", ""),
        sample_size=context.get("sample_size", ""),
        extractable_rate=_pct(metrics.extractable_rate),
        mean_direct_effects_per_doc=f"{metrics.mean_direct_effects_per_doc:.4f}",
        mean_moderations_per_doc=f"{metrics.mean_moderations_per_doc:.4f}",
        direct_effect_validation_rate=_pct(metrics.direct_effect_validation_rate),
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
