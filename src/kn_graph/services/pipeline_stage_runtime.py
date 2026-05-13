from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from kn_graph.config import Settings
from kn_graph.services import pipeline_runtime
from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services.pipeline_stage_queue import start_stage_pool


def _load_job_context(service: PipelineService, job_id: str) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    store = service._ensure_store()
    row = store.get_job(job_id) if hasattr(store, "get_job") else None
    if not isinstance(row, dict):
        raise RuntimeError(f"job_not_found:{job_id}")
    input_pdf = Path(str(row.get("input_path", "") or "")).resolve()
    if not input_pdf.exists():
        raise RuntimeError(f"input_missing:{input_pdf}")
    options_raw = str(row.get("options_json", "") or "{}")
    try:
        options = json.loads(options_raw)
        if not isinstance(options, dict):
            options = {}
    except Exception:
        options = {}
    options = pipeline_runtime._inject_pipeline_settings(options)
    job_root_raw = str(options.get("_job_root", "") or "").strip()
    run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (service._runs_root / job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    return row, options, input_pdf, run_dir


def _enqueue_next(service: PipelineService, *, job_id: str, stage: str, input_json: dict[str, Any]) -> None:
    service.enqueue_stage_task(
        {
            "job_id": job_id,
            "stage": stage,
            "status": "queued",
            "priority": 100,
            "attempt": 0,
            "max_attempts": 3,
            "idempotency_key": f"{job_id}:{stage}",
            "input_json": input_json,
        }
    )


def _handler_mineru_parse(service: PipelineService, task: dict[str, Any], _should_stop) -> dict[str, Any]:
    job_id = str(task.get("job_id", "") or "")
    store = service._ensure_store()
    _, options, input_pdf, run_dir = _load_job_context(service, job_id)
    parse_meta = pipeline_runtime._run_parse_pdf(job_id, input_pdf, run_dir, store, options)
    _enqueue_next(
        service,
        job_id=job_id,
        stage="paper_extract",
        input_json={"parse_meta": parse_meta},
    )
    return {"parse_meta": parse_meta}


def _handler_paper_extract(service: PipelineService, task: dict[str, Any], _should_stop) -> dict[str, Any]:
    job_id = str(task.get("job_id", "") or "")
    store = service._ensure_store()
    _, options, input_pdf, run_dir = _load_job_context(service, job_id)
    task_input = task.get("input_json", {})
    parse_meta = task_input.get("parse_meta", {}) if isinstance(task_input, dict) else {}
    import_result, workspace_path, library_id = pipeline_runtime._run_materialize_import(
        job_id=job_id,
        input_pdf=input_pdf,
        parse_meta=parse_meta,
        run_dir=run_dir,
        store=store,
        options=options,
    )
    imported_count = int(import_result.get("imported_count", 0) or 0)
    if imported_count <= 0:
        raise RuntimeError("import_noop:imported_count_is_zero")
    mats = import_result.get("materialized_papers", []) or []
    mat0 = mats[0] if isinstance(mats, list) and mats else {}
    materialized_md_path = pipeline_runtime._resolve_materialized_md_path(mat0 if isinstance(mat0, dict) else {})
    options["_workspace_path"] = workspace_path
    options["_materialized_md_path"] = materialized_md_path
    extract_result = pipeline_runtime._run_agent_extraction(job_id, parse_meta, run_dir, store, options)
    next_input = {
        "parse_meta": parse_meta,
        "extract_result": extract_result,
        "import_result": import_result,
        "workspace_path": workspace_path,
        "library_id": library_id,
        "imported_count": imported_count,
        "agent_mode": True,
    }
    _enqueue_next(service, job_id=job_id, stage="embedding", input_json=next_input)
    return next_input


def _handler_embedding(service: PipelineService, task: dict[str, Any], _should_stop) -> dict[str, Any]:
    job_id = str(task.get("job_id", "") or "")
    store = service._ensure_store()
    _, options, input_pdf, run_dir = _load_job_context(service, job_id)
    task_input = task.get("input_json", {})
    if not isinstance(task_input, dict):
        task_input = {}
    parse_meta = task_input.get("parse_meta", {}) if isinstance(task_input.get("parse_meta"), dict) else {}
    extract_result = task_input.get("extract_result", {}) if isinstance(task_input.get("extract_result"), dict) else {}
    pipeline_runtime._run_finalize_after_import(
        job_id=job_id,
        input_pdf=input_pdf,
        parse_meta=parse_meta,
        extract_result=extract_result,
        run_dir=run_dir,
        store=store,
        options=options,
        import_result=task_input.get("import_result", {}) if isinstance(task_input.get("import_result"), dict) else {},
        workspace_path=str(task_input.get("workspace_path", "") or ""),
        library_id=str(task_input.get("library_id", "") or ""),
        imported_count=int(task_input.get("imported_count", 0) or 0),
    )
    return {"finalized": True}


def start_pipeline_stage_workers(settings: Settings) -> list[threading.Thread]:
    # Local import to avoid module-level thread dependency during import.
    import threading

    service = PipelineService(settings)
    parse_concurrency = max(1, int(os.getenv("PIPELINE_CONCURRENCY_PARSE", "6") or "6"))
    extract_concurrency = max(1, int(os.getenv("PIPELINE_CONCURRENCY_EXTRACT", "3") or "3"))
    embed_concurrency = max(1, int(os.getenv("PIPELINE_CONCURRENCY_EMBED", "8") or "8"))

    threads: list[threading.Thread] = []
    threads.extend(
        start_stage_pool(
            settings=settings,
            stage="mineru_parse",
            concurrency=parse_concurrency,
            worker_tag="parse",
            handler=lambda task, should_stop: _handler_mineru_parse(service, task, should_stop),
        )
    )
    threads.extend(
        start_stage_pool(
            settings=settings,
            stage="paper_extract",
            concurrency=extract_concurrency,
            worker_tag="extract",
            handler=lambda task, should_stop: _handler_paper_extract(service, task, should_stop),
        )
    )
    threads.extend(
        start_stage_pool(
            settings=settings,
            stage="embedding",
            concurrency=embed_concurrency,
            worker_tag="embed",
            handler=lambda task, should_stop: _handler_embedding(service, task, should_stop),
        )
    )
    return threads
