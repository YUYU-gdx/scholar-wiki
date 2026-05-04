from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


class JobStore(Protocol):
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _load_script_module(module_name: str, rel_path: str):
    module_path = _SCRIPTS_DIR / rel_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _maybe_load_run_extraction_mvp():
    return _load_script_module("smj_pipeline_run_extraction_mvp_for_kn_graph_runtime", "run_extraction_mvp.py")


def _maybe_load_provider_registry():
    return _load_script_module("smj_pipeline_provider_registry_for_kn_graph_runtime", "llm/provider_registry.py")


def _maybe_load_mineru_single_runner():
    return _load_script_module("smj_pipeline_mineru_single_runner_for_kn_graph_runtime", "mineru_single_pdf_runner.py")


def _maybe_load_literature_service_class():
    mod = _load_script_module("smj_pipeline_literature_service_for_kn_graph_runtime", "literature/service.py")
    return mod.LiteratureService


def _stage_update(store: JobStore, job_id: str, stage: str, progress: int, event: str, **extra: Any) -> None:
    existing = store.get_job(job_id) or {}
    if _norm_status(existing.get("status")) in TERMINAL_JOB_STATUSES and event != "cancelled":
        return
    payload = {"stage": stage, "progress": int(progress), "last_event": event}
    payload.update(extra)
    store.update_job(job_id, payload)


def _is_cancel_requested(store: JobStore, job_id: str) -> bool:
    row = store.get_job(job_id)
    return bool(row and row.get("requested_cancel"))


def _run_parse_pdf(job_id: str, input_pdf: Path, run_dir: Path, store: JobStore) -> dict[str, Any]:
    _stage_update(store, job_id, "parse_pdf", 5, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        raise RuntimeError("job_cancelled")

    runner_mod = _maybe_load_mineru_single_runner()
    opts_raw = store.get_job(job_id) or {}
    options = {}
    raw_options = str(opts_raw.get("options_json", "") or "").strip()
    if raw_options:
        try:
            obj = json.loads(raw_options)
            if isinstance(obj, dict):
                options = obj
        except Exception:
            options = {}

    def _progress(pct: int, _label: str) -> None:
        _stage_update(store, job_id, "parse_pdf", max(5, min(45, int(pct))), "stage_progress", status="running")

    def _cancel() -> bool:
        return _is_cancel_requested(store, job_id)

    try:
        meta = runner_mod.parse_single_pdf(
            input_pdf,
            run_dir,
            options=options,
            progress_cb=_progress,
            cancel_cb=_cancel,
        )
    except Exception as exc:
        code = getattr(exc, "code", "")
        if str(code) == "job_cancelled":
            raise RuntimeError("job_cancelled")
        if str(code):
            raise RuntimeError(f"{code}:{getattr(exc, 'detail', str(exc))}")
        raise
    _stage_update(store, job_id, "parse_pdf", 45, "stage_done", status="running")
    return meta


def _build_llm_client(run_mod: Any, options: dict[str, Any]) -> Any:
    provider = str(options.get("llm_provider", "")).strip().lower() or None
    model = str(options.get("llm_model", "")).strip() or None
    provider_options = {
        "api_key_env": str(options.get("llm_api_key_env", "")).strip() or None,
        "base_url": str(options.get("llm_base_url", "")).strip() or None,
        "api_key": str(options.get("llm_api_key", "")).strip() or None,
        "timeout_seconds": options.get("llm_timeout_seconds"),
        "temperature": options.get("llm_temperature"),
        "max_tokens": options.get("llm_max_tokens"),
        "max_retries": options.get("llm_max_retries"),
    }
    provider_options = {k: v for k, v in provider_options.items() if v not in (None, "")}
    try:
        registry_mod = _maybe_load_provider_registry()
        registry = registry_mod.ProviderRegistry()
        return registry.create_extraction_client(
            provider=provider,
            model=model,
            options=provider_options,
        )
    except Exception:
        return run_mod.NullLLMClient()


def _run_extract_entities(job_id: str, parse_meta: dict[str, Any], run_dir: Path, store: JobStore, options: dict[str, Any]) -> dict[str, Any]:
    _stage_update(store, job_id, "extract_entities", 55, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "extract_entities"})
        raise RuntimeError("job_cancelled")

    run_mod = _maybe_load_run_extraction_mvp()
    html_path = Path(str(parse_meta.get("html_path", "")))
    if not html_path.exists():
        raise RuntimeError(f"missing_html_for_extraction:{html_path}")

    extract_dir = run_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    raw_output_path = extract_dir / "raw_llm_outputs.jsonl"
    review_queue_path = extract_dir / "review_queue.jsonl"
    report_path = extract_dir / "acceptance_report.md"

    row = {"paper_id": job_id, "doi": f"job::{job_id}", "html": html_path.read_text(encoding="utf-8", errors="ignore")}
    client = _build_llm_client(run_mod, options)
    artifacts = run_mod.run(
        [row],
        sample_size=1,
        llm_client=client,
        project_root=Path.cwd(),
        review_queue_jsonl=review_queue_path,
        report_output_path=report_path,
        raw_output_jsonl=raw_output_path,
    )
    summary = artifacts.summary.to_dict()
    payload = {
        "summary": summary,
        "metrics": artifacts.metrics,
        "report_path": str(report_path),
        "raw_output_jsonl": str(raw_output_path),
        "review_queue_jsonl": str(review_queue_path),
    }
    (extract_dir / "extract_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _stage_update(store, job_id, "extract_entities", 90, "stage_done", status="running")
    return payload


def _run_finalize(
    job_id: str,
    input_pdf: Path,
    parse_meta: dict[str, Any],
    extract_result: dict[str, Any],
    run_dir: Path,
    store: JobStore,
    options: dict[str, Any],
) -> dict[str, Any]:
    _stage_update(store, job_id, "finalize", 95, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "finalize"})
        raise RuntimeError("job_cancelled")

    library_id = str(options.get("library_id", "") or "").strip()
    workspace_path = str(options.get("_workspace_path", "") or "").strip()
    import_result: dict[str, Any] = {}
    import_warning = ""
    graph_output_path = ""
    graph_updated = False
    graph_output_size = 0
    if library_id:
        try:
            _stage_update(store, job_id, "finalize", 97, "stage_progress", status="running")
            lit_cls = _maybe_load_literature_service_class()
            literature = lit_cls()
            manifest_path = run_dir / "import_manifest.jsonl"
            paper_id = str(options.get("paper_id", "") or f"job::{job_id}").strip()
            doi = str(options.get("doi", "") or f"job::{job_id}").strip()
            title = str(options.get("title", "") or input_pdf.stem or job_id).strip()
            row = {"paper_id": paper_id, "doi": doi, "title": title, "source_path": str(input_pdf.resolve())}
            manifest_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            import_result = literature.import_manifest(manifest_path=manifest_path, options={"library_id": library_id})
            workspace_path = str(import_result.get("workspace_path", "") or workspace_path)
        except Exception as exc:
            import_warning = str(exc)
            raise RuntimeError(f"import_failed:{import_warning}") from exc
    else:
        raise RuntimeError("import_failed:library_id_missing")

    imported_count = int(import_result.get("imported_count", 0) or 0)
    if imported_count <= 0:
        raise RuntimeError("import_noop:imported_count_is_zero")

    # Graph rebuild is handled separately via build_graph_views.py and
    # is no longer part of the per-job finalize step (SQLite-only path).
    graph_warning = ""
    graph_output_path = ""
    graph_updated = False
    graph_output_size = 0

    result = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "library_id": library_id,
        "workspace_path": workspace_path,
        "parse": parse_meta,
        "extract": extract_result,
        "import_result": import_result,
        "import_warning": import_warning,
        "graph_warning": graph_warning,
        "imported_paper_count": imported_count,
        "graph_updated": bool(graph_updated),
        "graph_output_path": graph_output_path,
        "graph_output_size": int(graph_output_size),
        "final_verdict": "success",
        "finished_at": _now_iso(),
    }
    out_path = run_dir / "result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store.update_job(
        job_id,
        {
            "status": "completed",
            "stage": "finalize",
            "progress": 100,
            "output_path": str(out_path),
            "result_json": _safe_json_dumps(result),
            "last_event": "completed",
        },
    )
    return result


def execute_pipeline(job_store: JobStore, job_id: str, input_path: str, options: dict[str, Any], runs_root: Path) -> None:
    job_root_raw = str(options.get("_job_root", "") or "").strip()
    run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (runs_root / job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    input_pdf = Path(input_path).resolve()
    try:
        parse_meta = _run_parse_pdf(job_id, input_pdf, run_dir, job_store)
        extract_result = _run_extract_entities(job_id, parse_meta, run_dir, job_store, options)
        _run_finalize(job_id, input_pdf, parse_meta, extract_result, run_dir, job_store, options)
    except Exception as exc:
        if "job_cancelled" in str(exc):
            job_store.update_job(
                job_id,
                {"status": "cancelled", "stage": str((job_store.get_job(job_id) or {}).get("stage", "parse_pdf")), "last_event": "cancelled"},
            )
            return
        detail = str(exc)
        code = "pipeline_failed"
        if ":" in detail:
            first = detail.split(":", 1)[0].strip()
            if first:
                code = first
        cur = job_store.get_job(job_id) or {}
        failed_stage = str(cur.get("stage", "") or "unknown")
        job_store.update_job(
            job_id,
            {
                "status": "failed",
                "error_code": code,
                "error_detail": detail,
                "stage": failed_stage,
                "last_event": "failed",
                "result_json": _safe_json_dumps(
                    {
                        "job_id": job_id,
                        "final_verdict": "failed",
                        "failure_stage": failed_stage,
                        "failure_code": code,
                        "failure_detail": detail,
                        "finished_at": _now_iso(),
                    }
                ),
            },
        )


def dispatch_inline(job_store: JobStore, job_id: str, input_path: str, options: dict[str, Any], runs_root: Path) -> None:
    t = threading.Thread(target=execute_pipeline, args=(job_store, job_id, input_path, options, runs_root), daemon=True)
    t.start()
