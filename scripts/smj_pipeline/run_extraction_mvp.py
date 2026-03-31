from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Iterator, Protocol


def _load_sibling_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_QUALIFIER_MOD = _load_sibling_module("smj_pipeline_extraction_qualifier", "extraction/qualifier.py")
_LOCATOR_MOD = _load_sibling_module("smj_pipeline_extraction_locator", "extraction/locator.py")
_EXTRACTOR_MOD = _load_sibling_module("smj_pipeline_extraction_extractor", "extraction/extractor.py")
_VALIDATOR_MOD = _load_sibling_module("smj_pipeline_extraction_validator", "extraction/validator.py")
_REVIEW_QUEUE_MOD = _load_sibling_module("smj_pipeline_extraction_review_queue", "extraction/review_queue.py")
_METRICS_MOD = _load_sibling_module("smj_pipeline_evaluation_metrics", "evaluation/metrics.py")
_ZHIPU_MOD = _load_sibling_module("smj_pipeline_llm_zhipu_client", "llm/zhipu_client.py")

classify_document = _QUALIFIER_MOD.classify_document
locate_main_model_evidence = _LOCATOR_MOD.locate_main_model_evidence
extract_records = _EXTRACTOR_MOD.extract_records
validate_relation_records = _VALIDATOR_MOD.validate_relation_records
build_review_queue = _REVIEW_QUEUE_MOD.build_review_queue
write_review_queue_jsonl = _REVIEW_QUEUE_MOD.write_review_queue_jsonl
calculate_metrics = _METRICS_MOD.calculate_metrics
render_report = _METRICS_MOD.render_report
ZhipuChatCompletionsClient = _ZHIPU_MOD.ZhipuChatCompletionsClient


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class NullLLMClient:
    def complete(self, prompt: str) -> str:
        raise RuntimeError("LLM client not configured. Provide --llm-response-json for offline test or inject a real client.")


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


def run(
    input_manifest: Path | str | Iterable[dict[str, object]],
    sample_size: int = 100,
    llm_client: LLMClient | None = None,
    postgres_repo: object | None = None,
    neo4j_repo: object | None = None,
    project_root: Path | str | None = None,
    review_queue_jsonl: Path | str | None = None,
    report_output_path: Path | str | None = None,
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
        "extracted_relations": 0,
        "complete_relations": 0,
        "hypotheses_total": 0,
        "hypotheses_correct": 0,
        "relations_with_theory": 0,
        "citations_total": 0,
        "citations_locatable": 0,
    }

    rejected_records_acc: list[object] = []

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
            bundle, rejected = _process_class_a_record(row, html, llm, postgres_repo, neo4j_repo)
            rejected_records_acc.extend(rejected)
            _accumulate_stats(stats, bundle)
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

    metrics_obj = calculate_metrics(stats)
    report = render_report(metrics_obj, {"run_id": "mvp-local", "sample_size": denominator_used})
    if report_output_path is not None:
        Path(report_output_path).write_text(report, encoding="utf-8")

    return RunArtifacts(summary=summary, metrics=asdict(metrics_obj), report_markdown=report)


def _process_class_a_record(
    row: dict[str, object],
    html: str,
    llm_client: LLMClient,
    postgres_repo: object | None,
    neo4j_repo: object | None,
) -> tuple[object, list[object]]:
    evidence_spans = locate_main_model_evidence(html)
    bundle = extract_records(evidence_spans, llm_client)

    validation = validate_relation_records(bundle.relations)
    bundle.relations = validation.accepted_records

    paper_id = str(row.get("paper_id") or row.get("doi") or "")
    payload = {
        "relations": bundle.relations,
        "variable_level_theory_grounding": bundle.variable_level_theory_grounding,
        "relation_level_theory_grounding": bundle.relation_level_theory_grounding,
        "hypotheses": bundle.hypotheses,
        "citations": bundle.citations,
    }
    if paper_id and postgres_repo is not None:
        getattr(postgres_repo, "replace_paper_bundle")(paper_id, payload)
    if paper_id and neo4j_repo is not None:
        getattr(neo4j_repo, "project_bundle")(paper_id, payload)

    return bundle, validation.rejected_records


def _accumulate_stats(stats: dict[str, int], bundle: object) -> None:
    relations = list(getattr(bundle, "relations", []))
    hypotheses = list(getattr(bundle, "hypotheses", []))
    rel_theory = list(getattr(bundle, "relation_level_theory_grounding", []))
    citations = list(getattr(bundle, "citations", []))

    stats["extracted_relations"] += len(relations)
    stats["complete_relations"] += sum(1 for r in relations if _is_complete_relation(r))
    stats["hypotheses_total"] += len(hypotheses)
    stats["hypotheses_correct"] += sum(1 for h in hypotheses if _has_valid_verification(h))
    stats["relations_with_theory"] += _count_relations_with_theory(relations, rel_theory)
    stats["citations_total"] += len(citations)
    stats["citations_locatable"] += sum(1 for c in citations if _is_citation_locatable(c))


def _is_complete_relation(row: dict[str, object]) -> bool:
    required = ("source_var", "target_var", "relation_type", "model_tag", "direction", "verification", "evidence_anchor")
    return all(str(row.get(k, "")).strip() for k in required)


def _has_valid_verification(row: dict[str, object]) -> bool:
    allowed = {"supported", "partially_supported", "not_supported"}
    return str(row.get("verification", "")).strip() in allowed


def _count_relations_with_theory(relations: list[dict[str, object]], rel_theory: list[dict[str, object]]) -> int:
    theory_pairs = {
        (str(t.get("source_var", "")), str(t.get("target_var", "")))
        for t in rel_theory
        if str(t.get("source_var", "")).strip() and str(t.get("target_var", "")).strip()
    }
    return sum(
        1
        for r in relations
        if (str(r.get("source_var", "")), str(r.get("target_var", ""))) in theory_pairs
    )


def _is_citation_locatable(row: dict[str, object]) -> bool:
    allowed_sections = {"background", "hypothesis", "discussion"}
    section = str(row.get("section_tag", "")).strip().lower()
    return section in allowed_sections


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
        with path.open("r", encoding="utf-8") as handle:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run extraction MVP over a local manifest JSONL.")
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--review-queue-jsonl", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--llm-provider", choices=["zhipu"], default="zhipu")
    parser.add_argument("--llm-model", default="glm-4.5-flash")
    parser.add_argument("--llm-api-key-env", default="ZHIPU_API_KEY")
    parser.add_argument("--llm-base-url", default="https://open.bigmodel.cn/api/paas/v4/chat/completions")
    return parser.parse_args()


def _build_default_llm_client(args: argparse.Namespace) -> LLMClient:
    provider = str(args.llm_provider).strip().lower()
    if provider != "zhipu":
        raise ValueError(f"unsupported llm provider: {provider}")

    env_name = str(args.llm_api_key_env).strip()
    api_key = os.getenv(env_name, "").strip()
    if not api_key:
        raise RuntimeError(f"missing API key in environment variable: {env_name}")

    return ZhipuChatCompletionsClient(
        api_key=api_key,
        model=str(args.llm_model).strip(),
        base_url=str(args.llm_base_url).strip(),
    )


def main() -> None:
    args = parse_args()
    llm_client = _build_default_llm_client(args)
    artifacts = run(
        args.input_manifest,
        sample_size=args.sample_size,
        llm_client=llm_client,
        review_queue_jsonl=args.review_queue_jsonl,
        report_output_path=args.report_output,
    )
    print(json.dumps({"summary": artifacts.summary.to_dict(), "metrics": artifacts.metrics}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
