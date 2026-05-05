from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from kn_graph.providers.registry import ProviderRegistry
from kn_graph.services.extraction_pipeline import run as run_extraction_mvp, NullLLMClient
from kn_graph.services.graph_builder import _build_artifact_from_sqlite, run_build_from_artifact
from kn_graph.services.import_sqlite import main_inline as _import_sqlite_main_inline
from kn_graph.services.mineru_runner import parse_single_pdf
from kn_graph.services.sqlite_repo import SqliteRepo

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


class JobStore(Protocol):
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))




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


def _run_parse_pdf(job_id: str, input_pdf: Path, run_dir: Path, store: JobStore, options: dict[str, Any] | None = None) -> dict[str, Any]:
    _stage_update(store, job_id, "parse_pdf", 5, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        raise RuntimeError("job_cancelled")

    # Merge injected settings on top of stored options
    merged = dict(options or {})
    opts_raw = store.get_job(job_id) or {}
    raw_options = str(opts_raw.get("options_json", "") or "").strip()
    if raw_options:
        try:
            obj = json.loads(raw_options)
            if isinstance(obj, dict):
                merged = {**obj, **merged}
        except Exception:
            pass

    def _progress(pct: int, _label: str) -> None:
        _stage_update(store, job_id, "parse_pdf", max(5, min(45, int(pct))), "stage_progress", status="running")

    def _cancel() -> bool:
        return _is_cancel_requested(store, job_id)

    try:
        meta = parse_single_pdf(
            input_pdf,
            run_dir,
            options=merged,
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


def _build_llm_client(options: dict[str, Any]) -> Any:
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
        registry = ProviderRegistry()
        return registry.create_extraction_client(
            provider=provider,
            model=model,
            options=provider_options,
        )
    except Exception:
        return NullLLMClient()


def _run_extract_entities(job_id: str, parse_meta: dict[str, Any], run_dir: Path, store: JobStore, options: dict[str, Any]) -> dict[str, Any]:
    _stage_update(store, job_id, "extract_entities", 55, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "extract_entities"})
        raise RuntimeError("job_cancelled")

    html_path = Path(str(parse_meta.get("html_path", "")))
    if not html_path.exists():
        raise RuntimeError(f"missing_html_for_extraction:{html_path}")

    extract_dir = run_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    raw_output_path = extract_dir / "raw_llm_outputs.jsonl"
    review_queue_path = extract_dir / "review_queue.jsonl"
    report_path = extract_dir / "acceptance_report.md"

    row = {"paper_id": job_id, "doi": f"job::{job_id}", "html": html_path.read_text(encoding="utf-8", errors="ignore")}
    client = _build_llm_client(options)
    artifacts = run_extraction_mvp(
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
            from kn_graph.services.literature_service import LiteratureService
            literature = LiteratureService(settings=_pipeline_settings)
            manifest_path = run_dir / "import_manifest.jsonl"
            paper_id = str(options.get("paper_id", "") or f"job::{job_id}").strip()
            doi = str(options.get("doi", "") or f"job::{job_id}").strip()
            title = str(options.get("title", "") or input_pdf.stem or job_id).strip()
            parsed_html = parse_meta.get("html_path", "") or ""
            row = {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "offline_html_path": str(parsed_html),
                "source_path": str(input_pdf.resolve()),
            }
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

    # ── Persist paper metadata to SQLite from import result ──
    graph_warning = ""
    graph_output_path = ""
    graph_updated = False
    graph_output_size = 0
    if workspace_path:
        try:
            import sqlite3 as _sqlite3
            import json as _json
            db_path = Path(workspace_path) / "kn_gragh.db"
            conn = _sqlite3.connect(str(db_path))
            repo = SqliteRepo(conn)
            repo.apply_schema()

            mats = import_result.get("materialized_papers", []) or []
            mat_paper_key = str((mats[0] or {}).get("paper_key", "") if mats else "").strip()

            # Import extraction results into SQLite first (writes paper metadata + variables)
            raw_jsonl = run_dir / "extract" / "raw_llm_outputs.jsonl"
            if raw_jsonl.exists():
                # Align extraction paper_id with the materialized paper_key from import
                # so extraction data and file paths reference the same paper record.
                mats_list = import_result.get("materialized_papers", []) or []
                mat_paper_key = str((mats_list[0] or {}).get("paper_key", "") if mats_list else "").strip()
                if mat_paper_key:
                    fixed_path = run_dir / "extract" / "raw_llm_outputs_fixed.jsonl"
                    with open(raw_jsonl, "r", encoding="utf-8") as fin, open(str(fixed_path), "w", encoding="utf-8") as fout:
                        for line in fin:
                            line = line.strip()
                            if not line:
                                continue
                            obj = json.loads(line)
                            obj["paper_id"] = mat_paper_key
                            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    raw_jsonl = fixed_path
                _stage_update(store, job_id, "finalize", 98, "importing_to_sqlite", status="running")
                _import_sqlite_main_inline(db_path=str(db_path), raw_output_jsonl=raw_jsonl, apply_schema=False)
            # Write paper file paths (UPDATE to preserve extraction metadata)
            cur = conn.cursor()
            for m in mats:
                if not isinstance(m, dict):
                    continue
                pid = str(m.get("paper_id", "") or m.get("paper_key", "") or "").strip()
                if not pid:
                    continue
                meta_path = Path(str(m.get("meta_path", "") or ""))
                meta = {}
                if meta_path.exists():
                    try:
                        meta = _json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                title = str(meta.get("title", "") or "").strip() or str(m.get("title", "") or str(m.get("paper_key", "")) or "").strip()
                # Use UPDATE to avoid clearing extraction fields (extractability etc.)
                cur.execute(
                    """UPDATE papers SET doi = ?, title = ?,
                       offline_html_path = ?, source_pdf_path = ?, source_md_path = ?,
                       source_html_path = ?, metadata_source = ?
                       WHERE paper_id = ?""",
                    (
                        str(m.get("doi", "") or ""),
                        title,
                        str(m.get("html_path", "") or ""),
                        str(m.get("source_pdf_path", "") or ""),
                        str(m.get("md_library_path", "") or m.get("md_path", "") or ""),
                        str(m.get("html_path", "") or ""),
                        "literature_import",
                        pid,
                    ),
                )
            conn.commit()
            conn.close()
            # Always rebuild graph_views — paper metadata is now in SQLite
            _stage_update(store, job_id, "finalize", 99, "building_graph_views", status="running")
            artifact = _build_artifact_from_sqlite(db_path)
            views_out = Path(workspace_path) / "graph_views.json"
            run_build_from_artifact(artifact, views_out)
            graph_output_path = str(views_out.resolve())
            graph_updated = views_out.exists()
            if graph_updated:
                graph_output_size = views_out.stat().st_size
        except Exception as exc:
            graph_warning = str(exc)

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


_pipeline_settings: Any = None


def init_pipeline_settings(settings: Any) -> None:
    global _pipeline_settings
    _pipeline_settings = settings


def _inject_pipeline_settings(options: dict[str, Any]) -> dict[str, Any]:
    """Read pipeline settings from the Settings object and inject into options."""
    global _pipeline_settings
    settings = _pipeline_settings
    out = dict(options)

    if settings is None:
        if not out.get("llm_timeout_seconds"):
            out["llm_timeout_seconds"] = 300
        return out

    # mineru_api_key — this was missing before, causing the 5% failure
    if not str(out.get("mineru_api_key", "") or "").strip():
        val = str(getattr(settings, "mineru_api_key", "") or "").strip()
        if val:
            out["mineru_api_key"] = val

    # LLM provider / model / key from pipeline extraction settings
    if not str(out.get("llm_provider", "") or "").strip():
        val = str(getattr(settings, "pipeline_fast_provider", "") or "").strip()
        if val:
            out["llm_provider"] = val

    if not str(out.get("llm_model", "") or "").strip():
        val = str(getattr(settings, "pipeline_fast_model", "") or "").strip()
        if val:
            out["llm_model"] = val

    if not str(out.get("llm_api_key", "") or "").strip():
        val = str(getattr(settings, "deepseek_api_key", "") or "").strip()
        if val:
            out["llm_api_key"] = val

    if not str(out.get("llm_base_url", "") or "").strip():
        val = str(getattr(settings, "pipeline_fast_endpoint_url", "") or "").strip()
        if val:
            out["llm_base_url"] = val

    if not out.get("llm_timeout_seconds"):
        out["llm_timeout_seconds"] = 300

    return out


def execute_pipeline(job_store: JobStore, job_id: str, input_path: str, options: dict[str, Any], runs_root: Path) -> None:
    options = _inject_pipeline_settings(options)
    job_root_raw = str(options.get("_job_root", "") or "").strip()
    run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (runs_root / job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    input_pdf = Path(input_path).resolve()
    try:
        parse_meta = _run_parse_pdf(job_id, input_pdf, run_dir, job_store, options)
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
