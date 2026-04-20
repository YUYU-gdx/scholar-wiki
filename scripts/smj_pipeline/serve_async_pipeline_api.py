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
import threading
from typing import Any, Callable, Protocol
import uuid

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class JobStore(Protocol):
    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_job(self, job_id: str) -> dict[str, Any] | None: ...

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...

    def request_cancel(self, job_id: str) -> dict[str, Any]: ...


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
            self._jobs[job_id].update(dict(updates))
            self._jobs[job_id]["updated_at"] = _now_iso()
            return dict(self._jobs[job_id])

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            self._jobs[job_id]["requested_cancel"] = True
            self._jobs[job_id]["updated_at"] = _now_iso()
            return dict(self._jobs[job_id])


class PostgresJobStore:
    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn = dsn
        self._psycopg = psycopg
        self._ensure_table()

    def _conn(self):
        return self._psycopg.connect(self._dsn)

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
            requested_cancel boolean not null default false,
            idempotency_key text not null default '',
            last_event text not null default 'accepted',
            created_at timestamptz not null,
            updated_at timestamptz not null
        );
        create index if not exists idx_pipeline_jobs_updated_at on pipeline_jobs(updated_at);
        create unique index if not exists idx_pipeline_jobs_idempotency on pipeline_jobs(idempotency_key) where idempotency_key <> '';
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into pipeline_jobs (
                        job_id, status, stage, progress, error_code, error_detail, input_path, output_path,
                        options_json, result_json, requested_cancel, idempotency_key, last_event, created_at, updated_at
                    )
                    values (%(job_id)s, %(status)s, %(stage)s, %(progress)s, %(error_code)s, %(error_detail)s, %(input_path)s, %(output_path)s,
                            %(options_json)s, %(result_json)s, %(requested_cancel)s, %(idempotency_key)s, %(last_event)s, %(created_at)s, %(updated_at)s)
                    """,
                    row,
                )
            conn.commit()
        return row

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select job_id,status,stage,progress,error_code,error_detail,input_path,output_path,
                           options_json,result_json,requested_cancel,idempotency_key,last_event,created_at,updated_at
                    from pipeline_jobs where job_id=%s
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        keys = [
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
        ]
        out = dict(zip(keys, row, strict=False))
        return out

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not updates:
            existing = self.get_job(job_id)
            if existing is None:
                raise KeyError(job_id)
            return existing
        payload = dict(updates)
        payload["updated_at"] = _now_iso()
        sets = ", ".join(f"{k}=%({k})s" for k in payload.keys())
        params = dict(payload)
        params["job_id"] = job_id
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"update pipeline_jobs set {sets} where job_id=%(job_id)s", params)
                if cur.rowcount <= 0:
                    raise KeyError(job_id)
            conn.commit()
        refreshed = self.get_job(job_id)
        if refreshed is None:
            raise KeyError(job_id)
        return refreshed

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        return self.update_job(job_id, {"requested_cancel": True})


def _build_job_store() -> JobStore:
    dsn = str(os.getenv("PIPELINE_JOB_STORE_DSN", "")).strip()
    if dsn:
        return PostgresJobStore(dsn)
    return InMemoryJobStore()


def _maybe_load_run_extraction_mvp():
    module_path = Path(__file__).resolve().parent / "run_extraction_mvp.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_run_extraction_mvp_for_async_api", module_path)
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


def _stage_update(store: JobStore, job_id: str, stage: str, progress: int, event: str, **extra: Any) -> None:
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
    provider = str(options.get("llm_provider", "zhipu")).strip().lower()
    model = str(options.get("llm_model", "")).strip()
    if provider == "nvidia":
        key_env = str(options.get("llm_api_key_env", "NVIDIA_API_KEY")).strip() or "NVIDIA_API_KEY"
        api_key = str(os.getenv(key_env, "")).strip()
        base_url = str(options.get("llm_base_url", "https://integrate.api.nvidia.com/v1/chat/completions")).strip()
        if not api_key:
            return run_mod.NullLLMClient()
        model_name = model or "z-ai/glm4.7"
        return run_mod.NvidiaChatCompletionsClient(api_key=api_key, model=model_name, base_url=base_url)
    key_env = str(options.get("llm_api_key_env", "ZHIPU_API_KEY")).strip() or "ZHIPU_API_KEY"
    api_key = str(os.getenv(key_env, "")).strip()
    if not api_key:
        return run_mod.NullLLMClient()
    model_name = model or "glm-4.5-flash"
    return run_mod.ZhipuChatCompletionsClient(api_key=api_key, model=model_name)


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


def _run_finalize(job_id: str, parse_meta: dict[str, Any], extract_result: dict[str, Any], run_dir: Path, store: JobStore) -> dict[str, Any]:
    _stage_update(store, job_id, "finalize", 95, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "finalize"})
        raise RuntimeError("job_cancelled")
    result = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "parse": parse_meta,
        "extract": extract_result,
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
    run_dir = runs_root / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        parse_meta = _run_parse_pdf(job_id, Path(input_path), run_dir, job_store)
        extract_result = _run_extract_entities(job_id, parse_meta, run_dir, job_store, options)
        _run_finalize(job_id, parse_meta, extract_result, run_dir, job_store)
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
        parse_meta = _run_parse_pdf(payload["job_id"], Path(str(payload["input_path"])), runs_root / payload["job_id"], store)
        payload["parse_meta"] = parse_meta
        return payload

    @app.task(name="smj_pipeline.task_extract_entities")
    def task_extract_entities(payload: dict[str, Any]) -> dict[str, Any]:
        store = _build_job_store()
        runs_root = Path(str(payload["runs_root"]))
        extract_res = _run_extract_entities(
            payload["job_id"],
            payload["parse_meta"],
            runs_root / payload["job_id"],
            store,
            dict(payload.get("options", {})),
        )
        payload["extract_result"] = extract_res
        return payload

    @app.task(name="smj_pipeline.task_finalize")
    def task_finalize(payload: dict[str, Any]) -> dict[str, Any]:
        store = _build_job_store()
        runs_root = Path(str(payload["runs_root"]))
        result = _run_finalize(
            payload["job_id"],
            payload["parse_meta"],
            payload["extract_result"],
            runs_root / payload["job_id"],
            store,
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

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/pipeline/parse-extract")
    async def create_parse_extract_job(
        file: UploadFile = File(...),
        options: str | None = Form(default=None),
    ) -> JSONResponse:
        if not file.filename:
            raise HTTPException(status_code=400, detail={"error": "file_required"})
        if not str(file.filename).lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail={"error": "pdf_only"})
        parsed_options: dict[str, Any] = {}
        if options and options.strip():
            try:
                parsed = json.loads(options)
            except Exception:
                return JSONResponse(status_code=400, content={"error": "invalid_options_json"})
            if not isinstance(parsed, dict):
                return JSONResponse(status_code=400, content={"error": "options_must_be_object"})
            parsed_options = parsed

        job_id = f"job_{uuid.uuid4().hex}"
        run_dir = root / job_id
        upload_name = file.filename or "upload.pdf"
        input_path = run_dir / "input" / upload_name
        file_hash, file_size = _save_upload(file, input_path)
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
        }
        store.create_job(payload)
        run_pipeline_fn(ctx, job_id, str(input_path), parsed_options)
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "queued",
                "sse_url": f"/v1/jobs/{job_id}/events",
                "result_url": f"/v1/jobs/{job_id}/result",
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
        updated = store.request_cancel(job_id)
        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "status": updated.get("status", ""),
                "cancel_requested": bool(updated.get("requested_cancel")),
            },
        )

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

    uvicorn.run("scripts.smj_pipeline.serve_async_pipeline_api:app", host=args.host, port=int(args.port), reload=False)


try:
    _build_celery_dispatcher()
except Exception:
    pass

celery_app = _CELERY_APP
app = create_app()


if __name__ == "__main__":
    main()
