from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol
from kn_graph.services.extraction.qualifier import classify_document
from kn_graph.services.extraction.locator import locate_main_model_evidence
from kn_graph.services.extraction.review_queue import build_review_queue, write_review_queue_jsonl
from kn_graph.services.extraction.validator import validate_relation_records

from kn_graph.services.extraction_extractor import extract_records_with_raw

from kn_graph.providers.zhipu import ZhipuChatCompletionsClient  # noqa: E402
from kn_graph.providers.nvidia import NvidiaChatCompletionsClient  # noqa: E402
from kn_graph.providers.registry import ProviderRegistry  # noqa: E402


class LLMClient(Protocol):
    def complete(self, user_content: str, system_prompt: str | None = None) -> str: ...


class NullLLMClient:
    def complete(self, user_content: str, system_prompt: str | None = None) -> str:
        _ = user_content, system_prompt
        raise RuntimeError("LLM client not configured.")


@dataclass(slots=True, eq=True)
class RunSummary:
    seen: int
    class_a_used: int
    class_b_skipped: int
    class_c_skipped: int
    denominator_used: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class RunArtifacts:
    summary: RunSummary
    metrics: dict[str, float]
    report_markdown: str


@dataclass(slots=True)
class _InlineRejectedRecord:
    record: dict[str, Any]
    reason_codes: list[str]


def run(
    input_manifest: Path | str | Iterable[dict[str, object]],
    sample_size: int = 100,
    llm_client: LLMClient | None = None,
    db_repo: object | None = None,
    neo4j_repo: object | None = None,
    project_root: Path | str | None = None,
    review_queue_jsonl: Path | str | None = None,
    report_output_path: Path | str | None = None,
    raw_output_jsonl: Path | str | None = None,
) -> RunArtifacts:
    if sample_size < 0:
        raise ValueError("sample_size must be non-negative")

    llm = llm_client or NullLLMClient()
    root = Path(project_root) if project_root is not None else Path.cwd()

    seen = 0
    class_a_used = 0
    class_b_skipped = 0
    class_c_skipped = 0
    denominator_used = 0

    stats = {
        "eligible_docs": 0,
        "extractable_yes_docs": 0,
        "direct_effects_total": 0,
        "moderations_total": 0,
        "interactions_total": 0,
        "validated_direct_effects": 0,
    }

    rejected_records_acc: list[object] = []
    raw_outputs: list[dict[str, Any]] = []

    for row in _iter_manifest_rows(input_manifest):
        if class_a_used >= sample_size:
            break

        seen += 1
        html = _resolve_html(row, root)
        qualification = classify_document(html)
        doc_class = getattr(qualification, "doc_class", "C")

        if doc_class == "B":
            class_b_skipped += 1
            continue

        denominator_used += 1
        stats["eligible_docs"] += 1

        if doc_class == "A":
            class_a_used += 1
            try:
                bundle, rejected, raw_record = _process_class_a_record(row, html, llm, db_repo, neo4j_repo)
                rejected_records_acc.extend(rejected)
                _accumulate_stats(stats, bundle)
                raw_outputs.append(raw_record)
            except Exception as exc:
                rejected_records_acc.append(
                    _InlineRejectedRecord(
                        record={
                            "paper_id": str(row.get("paper_id", "")),
                            "doi": str(row.get("doi", "")),
                            "error": str(exc),
                        },
                        reason_codes=["PROCESSING_ERROR"],
                    )
                )
                raw_outputs.append(
                    {
                        "paper_id": str(row.get("paper_id", "")),
                        "doi": str(row.get("doi", "")),
                        "status": "error",
                        "error": str(exc),
                    }
                )
        else:
            class_c_skipped += 1

    summary = RunSummary(
        seen=seen,
        class_a_used=class_a_used,
        class_b_skipped=class_b_skipped,
        class_c_skipped=class_c_skipped,
        denominator_used=denominator_used,
    )

    if review_queue_jsonl is not None:
        queue = build_review_queue(rejected_records_acc)
        write_review_queue_jsonl(queue, Path(review_queue_jsonl))
    if raw_output_jsonl is not None:
        _write_jsonl(Path(raw_output_jsonl), raw_outputs)

    metrics = {
        "extractable_rate": _ratio(stats["extractable_yes_docs"], stats["eligible_docs"]),
        "mean_direct_effects_per_doc": _ratio(stats["direct_effects_total"], stats["eligible_docs"]),
        "mean_moderations_per_doc": _ratio(stats["moderations_total"], stats["eligible_docs"]),
        "mean_interactions_per_doc": _ratio(stats["interactions_total"], stats["eligible_docs"]),
        "direct_effect_validation_rate": _ratio(stats["validated_direct_effects"], max(1, stats["direct_effects_total"])),
    }
    report = _render_report(metrics, {"run_id": "mvp-local", "sample_size": denominator_used})
    if report_output_path is not None:
        Path(report_output_path).write_text(report, encoding="utf-8")

    return RunArtifacts(summary=summary, metrics=metrics, report_markdown=report)


def _process_class_a_record(
    row: dict[str, object],
    html: str,
    llm_client: LLMClient,
    db_repo: object | None,
    neo4j_repo: object | None,
) -> tuple[object, list[object], dict[str, Any]]:
    evidence_spans = locate_main_model_evidence(html)
    bundle, raw_response = extract_records_with_raw(html, llm_client)

    validation = validate_relation_records(bundle.direct_effects)
    bundle.direct_effects = validation.accepted_records

    paper_id = str(row.get("paper_id") or row.get("doi") or "")
    payload = {
        "doi": str(row.get("doi") or paper_id),
        "offline_html_path": str(row.get("offline_html_path") or row.get("full_html_path") or ""),
        "article_url": str(row.get("article_url") or ""),
        "publication_date": str(row.get("publication_date") or row.get("pub_date") or ""),
        "online_date": str(row.get("online_date") or ""),
        "publication_year": _infer_publication_year(row),
        "paper_citation_count": _coerce_optional_int(row.get("paper_citation_count") or row.get("citation_count")),
        "metadata_source": "manifest_or_model",
        "paper_domains": list(getattr(bundle, "paper_domains", [])),
        "extractability_status": getattr(bundle, "extractability_status", ""),
        "paper_type": getattr(bundle, "paper_type", ""),
        "extractability_reason": getattr(bundle, "extractability_reason", ""),
        "extractability_evidence_section": getattr(bundle, "extractability_evidence_section", ""),
        "direct_effects": bundle.direct_effects,
        "variable_definitions": bundle.variable_definitions,
        "moderations": bundle.moderations,
        "interactions": bundle.interactions,
    }
    if paper_id and db_repo is not None:
        getattr(db_repo, "replace_paper_bundle")(paper_id, payload)
    if paper_id and neo4j_repo is not None:
        getattr(neo4j_repo, "project_bundle")(paper_id, payload)

    raw_record = {
        "paper_id": paper_id,
        "doi": str(row.get("doi", "")),
        "status": "ok",
        "evidence_spans": len(evidence_spans),
        "paper_domains": list(getattr(bundle, "paper_domains", [])),
        "raw_response": raw_response,
    }
    return bundle, validation.rejected_records, raw_record


def _accumulate_stats(stats: dict[str, int], bundle: object) -> None:
    status = str(getattr(bundle, "extractability_status", "")).strip().lower()
    direct_effects = list(getattr(bundle, "direct_effects", []))
    moderations = list(getattr(bundle, "moderations", []))
    interactions = list(getattr(bundle, "interactions", []))

    if status == "yes":
        stats["extractable_yes_docs"] += 1
    stats["direct_effects_total"] += len(direct_effects)
    stats["moderations_total"] += len(moderations)
    stats["interactions_total"] += len(interactions)
    stats["validated_direct_effects"] += len(direct_effects)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _render_report(metrics: dict[str, float], meta: dict[str, object]) -> str:
    lines = [
        "# SMJ Extraction MVP Report",
        "",
        f"- run_id: {meta.get('run_id', '')}",
        f"- sample_size: {meta.get('sample_size', 0)}",
        "",
        "## Metrics",
    ]
    for k, v in metrics.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def _resolve_html(row: dict[str, object], project_root: Path) -> str:
    html = str(row.get("html", "") or "")
    if html.strip():
        return html

    for key in ("offline_html_path", "raw_html_path", "html_path", "full_html_path"):
        path_value = str(row.get(key, "") or "").strip()
        if not path_value:
            continue
        p = Path(path_value)
        if not p.is_absolute():
            p = project_root / p
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def _iter_manifest_rows(input_manifest: Path | str | Iterable[dict[str, object]]) -> Iterator[dict[str, object]]:
    if isinstance(input_manifest, (str, Path)):
        path = Path(input_manifest)
        with path.open("r", encoding="utf-8-sig") as handle:
            yield from _iter_jsonl_lines(handle)
        return

    for row in input_manifest:
        yield dict(row)


def _iter_jsonl_lines(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    for line in lines:
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("manifest rows must be JSON objects")
        yield payload


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def _infer_publication_year(row: dict[str, object]) -> int | None:
    direct = _coerce_optional_int(row.get("publication_year") or row.get("pub_year") or row.get("year"))
    if direct is not None:
        return direct
    for key in ("publication_date", "pub_date", "online_date"):
        v = str(row.get(key, "") or "").strip()
        if len(v) >= 4 and v[:4].isdigit():
            return int(v[:4])
    return None


def _coerce_optional_int(v: object) -> int | None:
    if v is None:
        return None
    text = str(v).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run extraction MVP over a local manifest JSONL.")
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--review-queue-jsonl", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--raw-output-jsonl", type=Path, default=None)
    parser.add_argument("--llm-provider", default="")
    parser.add_argument("--llm-model", default="glm-4.5")
    parser.add_argument("--llm-api-key-env", default="ZHIPU_API_KEY")
    parser.add_argument("--llm-base-url", default="https://open.bigmodel.cn/api/paas/v4/chat/completions")
    return parser.parse_args()


def _build_default_llm_client(args: argparse.Namespace) -> LLMClient:
    registry = ProviderRegistry()
    provider_options = {
        "api_key_env": str(args.llm_api_key_env or "").strip() or None,
        "base_url": str(args.llm_base_url or "").strip() or None,
    }
    provider_options = {k: v for k, v in provider_options.items() if v not in (None, "")}
    return registry.create_extraction_client(
        provider=str(args.llm_provider or "").strip() or None,
        model=str(args.llm_model or "").strip() or None,
        options=provider_options,
    )


def main() -> None:
    from kn_graph.config import Settings
    settings = Settings()
    settings.load_global_settings()
    args = parse_args()
    llm = _build_default_llm_client(args)
    artifacts = run(
        input_manifest=args.input_manifest,
        sample_size=args.sample_size,
        llm_client=llm,
        review_queue_jsonl=args.review_queue_jsonl,
        report_output_path=args.report_output,
        raw_output_jsonl=args.raw_output_jsonl,
    )

    print(
        json.dumps(
            {
                "summary": artifacts.summary.to_dict(),
                "metrics": artifacts.metrics,
                "report_path": str(args.report_output) if args.report_output else None,
                "review_queue_path": str(args.review_queue_jsonl) if args.review_queue_jsonl else None,
                "raw_output_path": str(args.raw_output_jsonl) if args.raw_output_jsonl else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
