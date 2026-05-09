from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import io

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services import pipeline_runtime


def _resolve_library_workspace(library_id: str, registry_path: str = "") -> Path:
    from kn_graph.services.library_registry import ensure_registry, resolve_workspace_root

    registry_path_arg = Path(registry_path) if registry_path else None
    registry = ensure_registry(registry_path=registry_path_arg)
    root = str(resolve_workspace_root(registry, library_id) or "").strip()
    if not root:
        raise RuntimeError(f"library_workspace_missing:{library_id}")
    path = Path(root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_upload(file: UploadFile, target: Path) -> tuple[str, int]:
    import asyncio

    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    size = 0
    with target.open("wb") as f:
        content = file.file.read()
        if content:
            f.write(content)
            hasher.update(content)
            size = len(content)
    return hasher.hexdigest(), size


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_router(pipeline_service: PipelineService) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["pipeline"])

    @router.get("/pipeline/health")
    async def pipeline_health():
        return pipeline_service.health()

    @router.post("/pipeline/parse-extract")
    async def create_parse_extract_job(
        file: UploadFile = File(...),
        library_id: str | None = Form(default=None),
        options: str | None = Form(default=None),
    ):
        lib = str(library_id or "").strip()
        if not lib:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        parsed_options: dict[str, Any] = {}
        if options and options.strip():
            try:
                parsed = json.loads(options)
                if not isinstance(parsed, dict):
                    return JSONResponse(status_code=400, content={"error": "options_must_be_object"})
                parsed_options = parsed
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"error": "invalid_options_json"})

        if not file.filename:
            return JSONResponse(status_code=400, content={"error": "file_required"})
        if not str(file.filename).lower().endswith(".pdf"):
            return JSONResponse(status_code=400, content={"error": "pdf_only"})

        try:
            registry_path = str(getattr(pipeline_service._settings, "registry_path", "") or "")
            try:
                workspace_root = _resolve_library_workspace(lib, registry_path)
            except TypeError:
                workspace_root = _resolve_library_workspace(lib)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"error": "library_workspace_missing", "detail": str(exc)})

        parsed_options["library_id"] = lib
        parsed_options["_workspace_path"] = str(workspace_root.resolve())

        job_id = f"job_{uuid.uuid4().hex}"
        runs_root = Path(str(getattr(pipeline_service, "_runs_root", workspace_root / "runs")))
        run_dir = runs_root / job_id
        upload_name = file.filename or "upload.pdf"
        input_path = run_dir / "input" / upload_name
        parsed_options["_job_root"] = str(run_dir.resolve())

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
            "library_id": lib,
            "workspace_path": str(workspace_root.resolve()),
            "source_job_id": "",
            "file_name": upload_name,
        }
        pipeline_service.create_job(payload)

        use_stage_queue = str(parsed_options.get("use_stage_queue", "") or "").strip().lower() in {"1", "true", "yes"}
        if not use_stage_queue:
            use_stage_queue = pipeline_service._settings.pipeline_executor.strip().lower() == "stage_queue"

        if use_stage_queue:
            pipeline_service.enqueue_stage_task(
                {
                    "job_id": job_id,
                    "stage": "mineru_parse",
                    "status": "queued",
                    "priority": 100,
                    "attempt": 0,
                    "max_attempts": 3,
                    "idempotency_key": f"{job_id}:mineru_parse",
                    "input_json": {},
                }
            )
        elif pipeline_service._settings.pipeline_executor.strip().lower() == "inline":
            store = pipeline_service._ensure_store()
            pipeline_runtime.dispatch_inline(
                store,
                job_id,
                str(input_path),
                dict(parsed_options),
                pipeline_service._runs_root,
            )

        return JSONResponse(status_code=202, content={
            "job_id": job_id,
            "status": "queued",
            "library_id": lib,
            "workspace_path": str(workspace_root.resolve()),
            "file_name": upload_name,
            "sse_url": f"/v1/jobs/{job_id}/events",
            "result_url": f"/v1/jobs/{job_id}/result",
        })

    @router.post("/pipeline/parse-extract/batch")
    async def create_parse_extract_batch(
        files: list[UploadFile] = File(default=[]),
        library_id: str | None = Form(default=None),
    ):
        lib = str(library_id or "").strip()
        if not lib:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        if not files:
            return JSONResponse(status_code=400, content={"error": "files_required"})
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for f in files:
            try:
                result = await create_parse_extract_job(file=f, library_id=lib, options=None)
                body = result.body if hasattr(result, "body") else {}
                if isinstance(body, dict):
                    accepted.append(body)
                elif isinstance(body, (bytes, bytearray)):
                    accepted.append(json.loads(body.decode("utf-8")))
                elif isinstance(body, str):
                    accepted.append(json.loads(body))
                else:
                    accepted.append({"file_name": str(getattr(f, "filename", "") or "")})
            except Exception as exc:
                rejected.append({"file_name": str(getattr(f, "filename", "") or ""), "error": str(exc)})
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

    @router.get("/jobs")
    async def list_jobs(
        page: int = Query(default=1),
        page_size: int = Query(default=50),
        status: str = Query(default=""),
        library_id: str = Query(default=""),
        q: str = Query(default=""),
        sort: str = Query(default="created_at_desc"),
    ):
        return pipeline_service.list_jobs(
            library_id=library_id,
            status=status,
            query=q,
            sort=sort,
            page=page,
            page_size=page_size,
        )

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        result = pipeline_service.get_job(job_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        return result

    @router.get("/jobs/{job_id}/stages")
    async def get_job_stages(job_id: str):
        result = pipeline_service.get_job_stages(job_id)
        if isinstance(result, dict) and result.get("error") == "job_not_found":
            return JSONResponse(status_code=404, content=result)
        return result

    @router.get("/jobs/{job_id}/result")
    async def get_job_result(job_id: str):
        result = pipeline_service.get_result(job_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        return result

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        result = pipeline_service.cancel_job(job_id)
        if "error" in result:
            error_code = result.get("error", "")
            if error_code == "job_not_found":
                return JSONResponse(status_code=404, content=result)
            if error_code == "job_not_cancellable":
                return JSONResponse(status_code=400, content=result)
            if error_code == "job_cancel_race_conflict":
                return JSONResponse(status_code=409, content=result)
        return result

    @router.post("/jobs/{job_id}/retry")
    async def retry_job(job_id: str):
        result = pipeline_service.retry_job(job_id)
        if result is None:
            row = pipeline_service.get_job(job_id)
            if row is None:
                return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
            source_path = pipeline_service.resolve_retry_source_pdf(row)
            if source_path is None:
                return JSONResponse(status_code=404, content={"error": "retry_source_pdf_missing", "job_id": job_id})
            lib = str(row.get("library_id", "") or "").strip()
            if not lib:
                return JSONResponse(status_code=400, content={"error": "library_id_missing", "job_id": job_id})
            raw_options = str(row.get("options_json", "") or "").strip()
            parsed_options: dict[str, Any] = {}
            if raw_options:
                try:
                    parsed = json.loads(raw_options)
                    if isinstance(parsed, dict):
                        parsed_options = parsed
                except Exception:
                    parsed_options = {}
            parsed_options.pop("_job_root", None)
            parsed_options.pop("_workspace_path", None)
            with source_path.open("rb") as fp:
                retry_upload = UploadFile(
                    filename=str(row.get("file_name", "") or source_path.name),
                    file=io.BytesIO(fp.read()),
                )
                created = await create_parse_extract_job(file=retry_upload, library_id=lib, options=json.dumps(parsed_options, ensure_ascii=False))
            payload: dict[str, Any]
            if isinstance(created.body, (bytes, bytearray)):
                payload = json.loads(created.body.decode("utf-8"))
            elif isinstance(created.body, str):
                payload = json.loads(created.body)
            else:
                payload = {}
            return JSONResponse(status_code=202, content={"source_job_id": job_id, "new_job": payload})
        if isinstance(result, dict) and "error" in result:
            if result.get("error") == "job_not_retryable":
                return JSONResponse(status_code=400, content=result)
        return result

    @router.delete("/jobs/{job_id}")
    async def delete_job(job_id: str):
        result = pipeline_service.delete_job(job_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        return result

    @router.get("/jobs/{job_id}/events")
    async def stream_job_events(job_id: str):
        async def event_generator():
            last_version = ""
            while True:
                row = pipeline_service.get_job(job_id)
                if row is None:
                    yield {"event": "failed", "data": json.dumps({"error": "job_not_found", "job_id": job_id}, ensure_ascii=False)}
                    break
                from kn_graph.services.pipeline_service import _public_job_payload

                version = f"{row.get('updated_at', '')}|{row.get('last_event', '')}"
                if version != last_version:
                    last_version = version
                    event = str(row.get("last_event", "stage_progress"))
                    valid_events = {"accepted", "stage_started", "stage_progress", "stage_done", "failed", "cancelled", "completed"}
                    if event not in valid_events:
                        event = "stage_progress"
                    yield {"event": event, "data": json.dumps(_public_job_payload(row), ensure_ascii=False)}
                status = str(row.get("status", ""))
                if status in {"completed", "failed", "cancelled"}:
                    break
                import asyncio

                await asyncio.sleep(0.8)

        return EventSourceResponse(event_generator())

    @router.get("/jobs/{job_id}/agent-events")
    async def stream_job_agent_events(job_id: str, cursor: int = Query(default=0)):
        async def event_generator():
            next_cursor = max(0, int(cursor))
            while True:
                payload = pipeline_service.get_agent_events(job_id=job_id, cursor=next_cursor, limit=200)
                if "error" in payload:
                    yield {"event": "failed", "data": json.dumps(payload, ensure_ascii=False)}
                    break
                events = payload.get("events", [])
                if isinstance(events, list):
                    for item in events:
                        yield {"event": "agent_event", "data": json.dumps(item, ensure_ascii=False)}
                next_cursor = int(payload.get("cursor", next_cursor) or next_cursor)
                if bool(payload.get("done", False)):
                    yield {"event": "agent_done", "data": json.dumps({"job_id": job_id, "cursor": next_cursor}, ensure_ascii=False)}
                    break
                import asyncio

                await asyncio.sleep(0.8)

        return EventSourceResponse(event_generator())

    return router
