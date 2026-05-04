from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Callable, Protocol
import uuid

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

RUNS_ROOT_DEFAULT = Path("outputs/runs")
JOB_EVENTS = {
    "accepted",
    "stage_started",
    "stage_progress",
    "stage_done",
    "failed",
    "cancelled",
    "completed",
}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _to_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_async_pipeline_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def _load_runtime_conventions():
    module_path = Path(__file__).resolve().parent / "runtime_conventions.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_runtime_conventions_for_async_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RUNTIME_CONVENTIONS = _load_runtime_conventions()


class JobStore(Protocol):
    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_job(self, job_id: str) -> dict[str, Any] | None: ...

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...

    def request_cancel(self, job_id: str) -> dict[str, Any]: ...

    def list_jobs(
        self,
        *,
        library_id: str = "",
        status: str = "",
        query: str = "",
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]: ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item = dict(payload)
            self._jobs[item["job_id"]] = item
            return dict(item)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            return dict(item) if isinstance(item, dict) else None

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            current = self._jobs[job_id]
            current_status = _norm_status(current.get("status"))
            payload = dict(updates)
            next_status = _norm_status(payload.get("status")) if "status" in payload else ""
            if current_status in TERMINAL_JOB_STATUSES:
                if not next_status:
                    return dict(current)
                if next_status != current_status:
                    return dict(current)
            current.update(payload)
            current["updated_at"] = _now_iso()
            return dict(current)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        return self.update_job(job_id, {"requested_cancel": True})

    def list_jobs(
        self,
        *,
        library_id: str = "",
        status: str = "",
        query: str = "",
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        lib = str(library_id or "").strip()
        st = str(status or "").strip().lower()
        q = str(query or "").strip().lower()
        with self._lock:
            rows = [dict(v) for v in self._jobs.values()]
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if lib and str(row.get("library_id", "") or "").strip() != lib:
                continue
            if st and str(row.get("status", "") or "").strip().lower() != st:
                continue
            if q:
                hay = " ".join(
                    [
                        str(row.get("job_id", "") or ""),
                        str(row.get("library_id", "") or ""),
                        str(row.get("file_name", "") or ""),
                        str(row.get("input_path", "") or ""),
                        str(row.get("error_detail", "") or ""),
                    ]
                ).lower()
                if q not in hay:
                    continue
            filtered.append(row)

        reverse = sort != "created_at_asc"
        filtered.sort(key=lambda x: str(x.get("created_at", "") or ""), reverse=reverse)
        total = len(filtered)
        start = max(0, (max(1, int(page)) - 1) * max(1, int(page_size)))
        end = start + max(1, int(page_size))
        return filtered[start:end], total


class SQLiteJobStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        ddl = """
        create table if not exists pipeline_jobs (
            job_id text primary key,
            status text not null,
            stage text not null,
            progress integer not null,
            error_code text not null default '',
            error_detail text not null default '',
            input_path text not null default '',
            output_path text not null default '',
            options_json text not null default '{}',
            result_json text not null default '{}',
            requested_cancel integer not null default 0,
            idempotency_key text not null default '',
            last_event text not null default 'accepted',
            created_at text not null,
            updated_at text not null,
            file_size integer not null default 0,
            file_hash text not null default '',
            library_id text not null default '',
            workspace_path text not null default '',
            source_job_id text not null default '',
            file_name text not null default ''
        );
        create index if not exists idx_pipeline_jobs_updated_at on pipeline_jobs(updated_at);
        create index if not exists idx_pipeline_jobs_created_at on pipeline_jobs(created_at);
        create index if not exists idx_pipeline_jobs_library_id on pipeline_jobs(library_id);
        create unique index if not exists idx_pipeline_jobs_idempotency on pipeline_jobs(idempotency_key) where idempotency_key <> '';
        """
        with self._conn() as conn:
            conn.executescript(ddl)
            conn.commit()

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload)
        columns = [
            "job_id",
            "status",
            "stage",
            "progress",
            "error_code",
            "error_detail",
            "input_path",
            "output_path",
            "options_json",
            "result_json",
            "requested_cancel",
            "idempotency_key",
            "last_event",
            "created_at",
            "updated_at",
            "file_size",
            "file_hash",
            "library_id",
            "workspace_path",
            "source_job_id",
            "file_name",
        ]
        values = {k: row.get(k, "") for k in columns}
        values["progress"] = int(values.get("progress", 0) or 0)
        values["requested_cancel"] = 1 if bool(values.get("requested_cancel")) else 0
        values["file_size"] = int(values.get("file_size", 0) or 0)
        with self._conn() as conn:
            conn.execute(
                f"insert into pipeline_jobs ({','.join(columns)}) values ({','.join(['?'] * len(columns))})",
                [values[k] for k in columns],
            )
            conn.commit()
        out = dict(values)
        out["requested_cancel"] = bool(out.get("requested_cancel"))
        return out

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("select * from pipeline_jobs where job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["requested_cancel"] = bool(out.get("requested_cancel"))
        return out

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not updates:
            row = self.get_job(job_id)
            if row is None:
                raise KeyError(job_id)
            return row
        payload = dict(updates)
        payload["updated_at"] = _now_iso()
        if "requested_cancel" in payload:
            payload["requested_cancel"] = 1 if bool(payload.get("requested_cancel")) else 0
        keys = list(payload.keys())
        sets = ",".join(f"{k}=?" for k in keys)
        guard_sql = "lower(status) not in (?,?,?)"
        guard_args: list[Any] = ["completed", "failed", "cancelled"]
        if "status" in payload:
            guard_sql = f"({guard_sql} or lower(status)=?)"
            guard_args.append(_norm_status(payload.get("status")))
        args = [payload[k] for k in keys] + [job_id] + guard_args
        with self._conn() as conn:
            cur = conn.execute(f"update pipeline_jobs set {sets} where job_id=? and {guard_sql}", args)
            if cur.rowcount <= 0:
                existing = conn.execute("select 1 from pipeline_jobs where job_id = ?", (job_id,)).fetchone()
                if existing is None:
                    raise KeyError(job_id)
            conn.commit()
        row = self.get_job(job_id)
        if row is None:
            raise KeyError(job_id)
        return row

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        return self.update_job(job_id, {"requested_cancel": True})

    def list_jobs(
        self,
        *,
        library_id: str = "",
        status: str = "",
        query: str = "",
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        args: list[Any] = []
        if str(library_id or "").strip():
            clauses.append("library_id = ?")
            args.append(str(library_id or "").strip())
        if str(status or "").strip():
            clauses.append("lower(status) = ?")
            args.append(str(status or "").strip().lower())
        if str(query or "").strip():
            q = f"%{str(query).strip().lower()}%"
            clauses.append("(lower(job_id) like ? or lower(file_name) like ? or lower(input_path) like ? or lower(error_detail) like ?)")
            args.extend([q, q, q, q])
        where = (" where " + " and ".join(clauses)) if clauses else ""
        order = "created_at asc" if sort == "created_at_asc" else "created_at desc"
        limit = max(1, int(page_size))
        offset = max(0, (max(1, int(page)) - 1) * limit)
        with self._conn() as conn:
            total = int(conn.execute(f"select count(*) from pipeline_jobs{where}", args).fetchone()[0])
            rows = conn.execute(
                f"select * from pipeline_jobs{where} order by {order} limit ? offset ?",
                args + [limit, offset],
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["requested_cancel"] = bool(item.get("requested_cancel"))
            out.append(item)
        return out, total


def _build_job_store() -> JobStore:
    kind = str(os.getenv("PIPELINE_JOB_STORE", "sqlite")).strip().lower()
    if kind == "memory":
        return InMemoryJobStore()
    sqlite_default_path = str(getattr(_RUNTIME_CONVENTIONS, "PIPELINE_SQLITE_DEFAULT_PATH", "outputs/workbench/pipeline_jobs.sqlite"))
    db_path_raw = str(os.getenv("PIPELINE_SQLITE_PATH", sqlite_default_path)).strip() or sqlite_default_path
    return SQLiteJobStore(Path(db_path_raw))


def _maybe_load_run_extraction_mvp():
    module_path = Path(__file__).resolve().parent / "run_extraction_mvp.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_run_extraction_mvp_for_async_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _maybe_load_provider_registry():
    module_path = Path(__file__).resolve().parent / "llm" / "provider_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_llm_provider_registry_for_async_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _maybe_load_mineru_single_runner():
    module_path = Path(__file__).resolve().parent / "mineru_single_pdf_runner.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_mineru_single_pdf_runner_for_async_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _maybe_load_library_registry_module():
    module_path = Path(__file__).resolve().parent / "library_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_library_registry_for_async_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _maybe_load_literature_service_class():
    module_path = Path(__file__).resolve().parent / "literature" / "service.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_literature_service_for_async_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LiteratureService


def _resolve_library_workspace(library_id: str) -> Path:
    lib = str(library_id or "").strip()
    if not lib:
        raise RuntimeError("library_id_required")
    try:
        _RUNTIME_CONVENTIONS.resolve_storage_root(require_initialized=True)
    except Exception as exc:
        raise RuntimeError(str(exc))
    lr_mod = _maybe_load_library_registry_module()
    registry = lr_mod.ensure_registry()
    root = str(lr_mod.resolve_workspace_root(registry, lib) or "").strip()
    if not root:
        raise RuntimeError(f"library_workspace_missing:{lib}")
    path = Path(root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_supported_source(filename: str) -> bool:
    suffix = Path(str(filename or "")).suffix.lower()
    return suffix in set(getattr(_RUNTIME_CONVENTIONS, "SUPPORTED_SOURCE_SUFFIXES", (".pdf",)))


def _save_upload(file: UploadFile, target: Path) -> tuple[str, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    size = 0
    with target.open("wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def _read_text_source(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    text = input_path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        return text
    if suffix == ".md":
        import html

        return f"<html><body><pre>{html.escape(text)}</pre></body></html>"
    import html

    return f"<html><body><pre>{html.escape(text)}</pre></body></html>"


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


def _run_prepare_readable(job_id: str, input_path: Path, run_dir: Path, store: JobStore) -> dict[str, Any]:
    _stage_update(store, job_id, "prepare_readable", 25, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        raise RuntimeError("job_cancelled")
    parse_dir = run_dir / "parse"
    parse_dir.mkdir(parents=True, exist_ok=True)
    parsed_md = parse_dir / "parsed.md"
    parsed_html = parse_dir / "parsed.html"
    content = input_path.read_text(encoding="utf-8", errors="ignore")
    if input_path.suffix.lower() == ".md":
        parsed_md.write_text(content, encoding="utf-8")
    else:
        parsed_md.write_text(content, encoding="utf-8")
    parsed_html.write_text(_read_text_source(input_path), encoding="utf-8")
    meta = {
        "markdown_path": str(parsed_md),
        "html_path": str(parsed_html),
        "source_kind": str(input_path.suffix.lower()),
    }
    (parse_dir / "parse_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _stage_update(store, job_id, "prepare_readable", 45, "stage_done", status="running")
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
    if library_id:
        try:
            _stage_update(store, job_id, "finalize", 97, "stage_progress", status="running")
            lit_cls = _maybe_load_literature_service_class()
            literature = lit_cls()
            manifest_path = run_dir / "import_manifest.jsonl"
            paper_id = str(options.get("paper_id", "") or f"job::{job_id}").strip()
            doi = str(options.get("doi", "") or f"job::{job_id}").strip()
            title = str(options.get("title", "") or input_pdf.stem or job_id).strip()
            row = {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "source_path": str(input_pdf.resolve()),
            }
            manifest_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            import_result = literature.import_manifest(manifest_path=manifest_path, options={"library_id": library_id})
            workspace_path = str(import_result.get("workspace_path", "") or workspace_path)
        except Exception as exc:
            import_warning = str(exc)

    # --- Graph rebuild skipped (SQLite-only, no central Postgres DB) ---
    graph_warning = ""

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
    if job_root_raw:
        run_dir = Path(job_root_raw).resolve() / "run"
    else:
        run_dir = runs_root / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    input_file = Path(input_path).resolve()
    try:
        if input_file.suffix.lower() == ".pdf":
            parse_meta = _run_parse_pdf(job_id, input_file, run_dir, job_store)
        else:
            parse_meta = _run_prepare_readable(job_id, input_file, run_dir, job_store)
        extract_result = _run_extract_entities(job_id, parse_meta, run_dir, job_store, options)
        _run_finalize(job_id, input_file, parse_meta, extract_result, run_dir, job_store, options)
    except Exception as exc:
        if "job_cancelled" in str(exc):
            job_store.update_job(
                job_id,
                {
                    "status": "cancelled",
                    "stage": str((job_store.get_job(job_id) or {}).get("stage", "parse_pdf")),
                    "last_event": "cancelled",
                },
            )
            return
        detail = str(exc)
        code = "pipeline_failed"
        if ":" in detail:
            first = detail.split(":", 1)[0].strip()
            if first:
                code = first
        job_store.update_job(
            job_id,
            {
                "status": "failed",
                "error_code": code,
                "error_detail": detail,
                "last_event": "failed",
            },
        )


@dataclass(slots=True)
class DispatchContext:
    job_store: JobStore
    runs_root: Path


def run_pipeline_inline(ctx: DispatchContext, job_id: str, input_path: str, options: dict[str, Any]) -> None:
    t = threading.Thread(target=execute_pipeline, args=(ctx.job_store, job_id, input_path, options, ctx.runs_root), daemon=True)
    t.start()


def _build_celery_objects():
    try:
        from celery import Celery, chain
    except Exception as exc:
        raise RuntimeError(f"celery_not_available:{exc}") from exc

    eager = _to_bool(os.getenv("PIPELINE_TASK_ALWAYS_EAGER"), default=False)
    broker = str(os.getenv("PIPELINE_REDIS_URL", "redis://127.0.0.1:6379/0")).strip()
    backend = str(os.getenv("PIPELINE_CELERY_BACKEND", broker)).strip()
    if eager:
        broker = "memory://"
        backend = "cache+memory://"
    app = Celery("smj_pipeline_async_pipeline", broker=broker, backend=backend)
    app.conf.update(task_always_eager=eager, task_serializer="json", accept_content=["json"], result_serializer="json")

    @app.task(name="smj_pipeline.task_parse_pdf")
    def task_parse_pdf(payload: dict[str, Any]) -> dict[str, Any]:
        store = _build_job_store()
        runs_root = Path(str(payload["runs_root"]))
        options = dict(payload.get("options", {}))
        job_root_raw = str(options.get("_job_root", "") or "").strip()
        run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (runs_root / payload["job_id"])
        input_file = Path(str(payload["input_path"]))
        if input_file.suffix.lower() == ".pdf":
            parse_meta = _run_parse_pdf(payload["job_id"], input_file, run_dir, store)
        else:
            parse_meta = _run_prepare_readable(payload["job_id"], input_file, run_dir, store)
        payload["parse_meta"] = parse_meta
        return payload

    @app.task(name="smj_pipeline.task_extract_entities")
    def task_extract_entities(payload: dict[str, Any]) -> dict[str, Any]:
        store = _build_job_store()
        runs_root = Path(str(payload["runs_root"]))
        options = dict(payload.get("options", {}))
        job_root_raw = str(options.get("_job_root", "") or "").strip()
        run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (runs_root / payload["job_id"])
        extract_res = _run_extract_entities(
            payload["job_id"],
            payload["parse_meta"],
            run_dir,
            store,
            options,
        )
        payload["extract_result"] = extract_res
        return payload

    @app.task(name="smj_pipeline.task_finalize")
    def task_finalize(payload: dict[str, Any]) -> dict[str, Any]:
        store = _build_job_store()
        runs_root = Path(str(payload["runs_root"]))
        options = dict(payload.get("options", {}))
        job_root_raw = str(options.get("_job_root", "") or "").strip()
        run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (runs_root / payload["job_id"])
        result = _run_finalize(
            payload["job_id"],
            Path(str(payload["input_path"])),
            payload["parse_meta"],
            payload["extract_result"],
            run_dir,
            store,
            options,
        )
        payload["result"] = result
        return payload

    def _dispatch(ctx: DispatchContext, job_id: str, input_path: str, options: dict[str, Any]) -> None:
        payload = {"job_id": job_id, "input_path": input_path, "options": options, "runs_root": str(ctx.runs_root)}
        chain(task_parse_pdf.s(payload), task_extract_entities.s(), task_finalize.s()).apply_async()

    return app, _dispatch


_CELERY_APP = None
_CELERY_DISPATCH = None


def _build_celery_dispatcher() -> Callable[[DispatchContext, str, str, dict[str, Any]], None]:
    global _CELERY_APP, _CELERY_DISPATCH
    if _CELERY_DISPATCH is None:
        _CELERY_APP, _CELERY_DISPATCH = _build_celery_objects()
    return _CELERY_DISPATCH


def _public_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    out = dict(job)
    for key in ("options_json", "result_json"):
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                out[key[:-5]] = json.loads(raw)
            except Exception:
                out[key[:-5]] = raw
    status = str(out.get("status", "") or "").strip().lower()
    stage = str(out.get("stage", "") or "").strip().lower()
    stage_label_map = {
        "accepted": "待处理",
        "parse_pdf": "解析中",
        "extract_entities": "抽取中",
        "finalize": "整理中",
    }
    display_name = str(out.get("file_name", "") or "").strip() or str(out.get("job_id", "") or "").strip()
    out["display_name"] = display_name
    out["status_code"] = status
    out["stage_code"] = stage
    out["stage_label"] = stage_label_map.get(stage, stage or "")
    out["can_cancel"] = status in {"queued", "running"}
    out["can_retry"] = status in {"failed", "cancelled"}
    return out


def create_app(
    job_store: JobStore | None = None,
    run_pipeline_fn: Callable[[DispatchContext, str, str, dict[str, Any]], None] | None = None,
    runs_root: Path | None = None,
) -> FastAPI:
    _ENV_UTILS.load_repo_env()
    store = job_store or _build_job_store()
    root = (runs_root or RUNS_ROOT_DEFAULT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if run_pipeline_fn is None:
        executor = str(os.getenv("PIPELINE_EXECUTOR", "celery")).strip().lower()
        if executor == "inline":
            run_pipeline_fn = run_pipeline_inline
        else:
            try:
                run_pipeline_fn = _build_celery_dispatcher()
            except Exception:
                run_pipeline_fn = run_pipeline_inline
    ctx = DispatchContext(job_store=store, runs_root=root)

    app = FastAPI(title="SMJ Async Pipeline API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/pipeline/health")
    def pipeline_health() -> dict[str, Any]:
        executor = str(os.getenv("PIPELINE_EXECUTOR", "celery")).strip().lower()
        return {
            "status": "ok",
            "executor": executor if executor in {"celery", "inline"} else "inline",
        }

    @app.get("/v1/storage/status")
    def storage_status() -> dict[str, Any]:
        suggested = _RUNTIME_CONVENTIONS.detect_default_storage_root()
        exists = suggested.exists()
        return {
            "initialized": bool(exists),
            "storage_root": str(suggested.resolve()),
            "requires_init": not bool(exists),
        }

    @app.post("/v1/storage/init")
    async def storage_init(storage_root: str | None = Form(default=None)) -> JSONResponse:
        chosen = str(storage_root or "").strip()
        path = Path(chosen).resolve() if chosen else _RUNTIME_CONVENTIONS.detect_default_storage_root()
        try:
            root = _RUNTIME_CONVENTIONS.ensure_storage_root(path)
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "storage_init_failed", "detail": str(exc)})
        os.environ["KN_STORAGE_ROOT"] = str(root)
        os.environ["LITERATURE_LIBRARY_WORKSPACES_ROOT"] = str((root / "libraries" / "workspaces").resolve())
        return JSONResponse(status_code=200, content={"initialized": True, "storage_root": str(root.resolve())})

    def _parse_options(options_text: str | None) -> dict[str, Any]:
        parsed_options: dict[str, Any] = {}
        if options_text and options_text.strip():
            try:
                parsed = json.loads(options_text)
            except Exception:
                raise HTTPException(status_code=400, detail={"error": "invalid_options_json"})
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400, detail={"error": "options_must_be_object"})
            parsed_options = parsed
        return parsed_options

    def _create_one_job(file: UploadFile, lib: str, base_options: dict[str, Any], source_job_id: str = "") -> dict[str, Any]:
        if not file.filename:
            raise HTTPException(status_code=400, detail={"error": "file_required"})
        if not _is_supported_source(str(file.filename)):
            raise HTTPException(status_code=400, detail={"error": "unsupported_source_type"})
        workspace_root = _resolve_library_workspace(lib)
        parsed_options = dict(base_options)
        parsed_options["library_id"] = lib
        job_id = f"job_{uuid.uuid4().hex}"
        run_dir = _RUNTIME_CONVENTIONS.build_job_root(workspace_root, job_id)
        upload_name = file.filename or "upload.pdf"
        input_path = _RUNTIME_CONVENTIONS.build_job_input_path(workspace_root, job_id, upload_name)
        parsed_options["_job_root"] = str(run_dir.resolve())
        parsed_options["_workspace_path"] = str(workspace_root.resolve())
        file_hash, file_size = _save_upload(file, input_path)
        source_archive = _RUNTIME_CONVENTIONS.build_source_archive_path(workspace_root, upload_name)
        source_archive.parent.mkdir(parents=True, exist_ok=True)
        if not source_archive.exists():
            source_archive.write_bytes(input_path.read_bytes())
        idempotency_key = hashlib.sha256((file_hash + ":" + _safe_json_dumps(parsed_options)).encode("utf-8")).hexdigest()
        now = _now_iso()
        payload = {
            "job_id": job_id,
            "status": "queued",
            "stage": "accepted",
            "progress": 0,
            "error_code": "",
            "error_detail": "",
            "input_path": str(input_path),
            "output_path": "",
            "options_json": _safe_json_dumps(parsed_options),
            "result_json": "{}",
            "requested_cancel": False,
            "idempotency_key": idempotency_key,
            "last_event": "accepted",
            "created_at": now,
            "updated_at": now,
            "file_size": file_size,
            "file_hash": file_hash,
            "library_id": lib,
            "workspace_path": str(workspace_root.resolve()),
            "source_job_id": str(source_job_id or "").strip(),
            "file_name": upload_name,
        }
        store.create_job(payload)
        run_pipeline_fn(ctx, job_id, str(input_path), parsed_options)
        return {
            "job_id": job_id,
            "status": "queued",
            "library_id": lib,
            "workspace_path": str(workspace_root.resolve()),
            "file_name": upload_name,
            "sse_url": f"/v1/jobs/{job_id}/events",
            "result_url": f"/v1/jobs/{job_id}/result",
        }

    @app.post("/v1/pipeline/parse-extract")
    async def create_parse_extract_job(
        file: UploadFile = File(...),
        library_id: str | None = Form(default=None),
        options: str | None = Form(default=None),
    ) -> JSONResponse:
        lib = str(library_id or "").strip()
        if not lib:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        try:
            parsed_options = _parse_options(options)
            return JSONResponse(status_code=202, content=_create_one_job(file=file, lib=lib, base_options=parsed_options))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
            return JSONResponse(status_code=exc.status_code, content=detail)
        except RuntimeError as exc:
            text = str(exc)
            if text.startswith("storage_root_not_initialized:"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "storage_not_initialized",
                        "detail": text,
                        "suggested_root": str(_RUNTIME_CONVENTIONS.detect_default_storage_root()),
                    },
                )
            return JSONResponse(status_code=500, content={"error": "create_job_failed", "detail": text})

    @app.post("/v1/pipeline/parse-extract/batch")
    async def create_parse_extract_batch_jobs(
        files: list[UploadFile] = File(default=[]),
        library_id: str | None = Form(default=None),
    ) -> JSONResponse:
        lib = str(library_id or "").strip()
        if not lib:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        if not files:
            return JSONResponse(status_code=400, content={"error": "files_required"})
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for file in files:
            try:
                accepted.append(_create_one_job(file=file, lib=lib, base_options={}))
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
                rejected.append({"file_name": str(getattr(file, "filename", "") or ""), **detail})
            except RuntimeError as exc:
                rejected.append({"file_name": str(getattr(file, "filename", "") or ""), "error": str(exc)})
            except Exception as exc:
                rejected.append({"file_name": str(getattr(file, "filename", "") or ""), "error": str(exc)})
        return JSONResponse(
            status_code=202 if accepted else 400,
            content={
                "library_id": lib,
                "accepted_count": len(accepted),
                "rejected_count": len(rejected),
                "accepted": accepted,
                "rejected": rejected,
            },
        )

    @app.get("/v1/jobs")
    async def list_jobs(
        page: int = 1,
        page_size: int = 50,
        status: str = "",
        library_id: str = "",
        q: str = "",
        sort: str = "created_at_desc",
    ) -> JSONResponse:
        rows, total = store.list_jobs(
            library_id=library_id,
            status=status,
            query=q,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(
            status_code=200,
            content={
                "jobs": [_public_job_payload(x) for x in rows],
                "total": int(total),
                "page": max(1, int(page)),
                "page_size": max(1, int(page_size)),
            },
        )

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> JSONResponse:
        row = store.get_job(job_id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        return JSONResponse(status_code=200, content=_public_job_payload(row))

    @app.get("/v1/jobs/{job_id}/result")
    async def get_result(job_id: str) -> JSONResponse:
        row = store.get_job(job_id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        if str(row.get("status", "")) != "completed":
            return JSONResponse(status_code=404, content={"error": "result_not_ready", "job_id": job_id, "status": row.get("status", "")})
        raw_result = str(row.get("result_json", "") or "{}")
        try:
            result = json.loads(raw_result)
        except Exception:
            result = {"raw": raw_result}
        return JSONResponse(status_code=200, content={"job_id": job_id, "status": "completed", "result": result})

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> JSONResponse:
        row = store.get_job(job_id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        cur_status = str(row.get("status", "") or "").strip().lower()
        if cur_status in {"completed", "failed", "cancelled"}:
            return JSONResponse(
                status_code=400,
                content={"error": "job_not_cancellable", "job_id": job_id, "status": str(row.get("status", "") or "")},
            )
        store.request_cancel(job_id)
        updated = store.update_job(
            job_id,
            {
                "status": "cancelled",
                "last_event": "cancelled",
                "error_code": "job_cancelled_by_user",
                "error_detail": "cancel requested by user",
            },
        )
        updated_status = _norm_status(updated.get("status"))
        if updated_status != "cancelled":
            return JSONResponse(
                status_code=409,
                content={"error": "job_cancel_race_conflict", "job_id": job_id, "status": str(updated.get("status", "") or "")},
            )
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "status": updated.get("status", ""),
                "cancel_requested": bool(updated.get("requested_cancel")),
            },
        )

    @app.post("/v1/jobs/{job_id}/retry")
    async def retry_job(job_id: str) -> JSONResponse:
        row = store.get_job(job_id)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        status = str(row.get("status", "") or "").strip().lower()
        if status not in {"failed", "cancelled"}:
            return JSONResponse(
                status_code=400,
                content={"error": "job_not_retryable", "job_id": job_id, "status": str(row.get("status", "") or "")},
            )
        source_path = Path(str(row.get("input_path", "") or "")).resolve()
        if not source_path.exists() or not source_path.is_file():
            return JSONResponse(status_code=404, content={"error": "input_file_missing", "job_id": job_id})
        lib = str(row.get("library_id", "") or "").strip()
        if not lib:
            return JSONResponse(status_code=400, content={"error": "library_id_missing", "job_id": job_id})

        raw_options = str(row.get("options_json", "") or "").strip()
        parsed_options: dict[str, Any] = {}
        if raw_options:
            try:
                parsed_options = json.loads(raw_options)
            except Exception:
                parsed_options = {}
        parsed_options.pop("_job_root", None)
        parsed_options.pop("_workspace_path", None)
        with source_path.open("rb") as fp:
            retry_upload = UploadFile(filename=str(row.get("file_name", "") or source_path.name), file=fp)
            payload = _create_one_job(file=retry_upload, lib=lib, base_options=parsed_options, source_job_id=job_id)
        return JSONResponse(status_code=202, content={"source_job_id": job_id, "new_job": payload})

    @app.get("/v1/jobs/{job_id}/events")
    async def stream_job_events(job_id: str):
        async def _iter():
            last_version = ""
            while True:
                row = store.get_job(job_id)
                if row is None:
                    yield "event: failed\ndata: " + json.dumps({"error": "job_not_found", "job_id": job_id}, ensure_ascii=False) + "\n\n"
                    break
                version = f"{row.get('updated_at','')}|{row.get('last_event','')}"
                if version != last_version:
                    last_version = version
                    event = str(row.get("last_event", "stage_progress"))
                    if event not in JOB_EVENTS:
                        event = "stage_progress"
                    yield f"event: {event}\n"
                    yield "data: " + json.dumps(_public_job_payload(row), ensure_ascii=False) + "\n\n"
                status = str(row.get("status", ""))
                if status in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.8)

        return StreamingResponse(_iter(), media_type="text/event-stream")

    return app


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serve async parse-extract API with FastAPI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8021)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    import uvicorn

    print(
        "[DEPRECATED] serve_async_pipeline_api.py is kept for compatibility only. "
        "Use: uv run python -m kn_graph serve --host 127.0.0.1 --port 8013"
    )
    uvicorn.run(app, host=args.host, port=int(args.port), reload=False)


try:
    _build_celery_dispatcher()
except Exception:
    pass

celery_app = _CELERY_APP
app = create_app()


if __name__ == "__main__":
    main()

