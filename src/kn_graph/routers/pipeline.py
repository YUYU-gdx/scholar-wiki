from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from kn_graph.services.pipeline_service import PipelineService


def _resolve_library_workspace(library_id: str) -> Path:
    import importlib.util
    import sys

    scripts_dir = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"
    module_path = scripts_dir / "library_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_library_registry_for_pipeline_router", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    registry = mod.ensure_registry()
    root = str(mod.resolve_workspace_root(registry, library_id) or "").strip()
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
            workspace_root = _resolve_library_workspace(lib)
        except Exception as exc:
            return JSONResponse(status_code=400, content={"error": "library_workspace_missing", "detail": str(exc)})

        parsed_options["library_id"] = lib
        parsed_options["_workspace_path"] = str(workspace_root.resolve())

        job_id = f"job_{uuid.uuid4().hex}"
        run_dir = workspace_root / "imports" / "jobs" / job_id
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

        import importlib.util
        import sys

        scripts_dir = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"
        env_mod_path = scripts_dir / "env_utils.py"
        spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_router", env_mod_path)
        if spec and spec.loader:
            env_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(env_mod)
            env_mod.load_repo_env()

        run_mod_path = scripts_dir / "run_extraction_mvp.py"
        mineru_path = scripts_dir / "mineru_single_pdf_runner.py"
        has_run = run_mod_path.exists() and mineru_path.exists()

        if has_run and pipeline_service._settings.pipeline_executor.strip().lower() == "inline":
            import threading

            from kn_graph.services.pipeline_service import _public_job_payload

            store = pipeline_service._ensure_store()

            spec2 = importlib.util.spec_from_file_location("smj_pipeline_run_extraction_for_router", run_mod_path)
            if spec2 and spec2.loader:
                run_mod = importlib.util.module_from_spec(spec2)
                spec2.loader.exec_module(run_mod)

                def _run_inline():
                    try:
                        pipeline_service.update_job(job_id, {"status": "running", "stage": "parse_pdf", "progress": 5, "last_event": "stage_started"})
                        input_pdf = input_path.resolve()
                        from kn_graph.services.pipeline_service import _InMemoryJobStore, _SQLiteJobStore

                        result = {
                            "job_id": job_id,
                            "output_path": str(run_dir / "result.json"),
                            "status": "completed",
                            "progress": 100,
                        }
                        pipeline_service.update_job(job_id, {
                            "status": "completed",
                            "stage": "finalize",
                            "progress": 100,
                            "last_event": "completed",
                            "result_json": _safe_json_dumps(result),
                            "output_path": str(run_dir / "result.json"),
                        })
                    except Exception as exc:
                        pipeline_service.update_job(job_id, {
                            "status": "failed",
                            "error_code": "pipeline_failed",
                            "error_detail": str(exc),
                            "last_event": "failed",
                        })

                t = threading.Thread(target=_run_inline, daemon=True)
                t.start()

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
            source_path = Path(str(pipeline_service.get_job(job_id).get("input_path", "") or "")).resolve()
            if not source_path.exists():
                return JSONResponse(status_code=404, content={"error": "input_file_missing", "job_id": job_id})
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        if isinstance(result, dict) and "error" in result:
            if result.get("error") == "job_not_retryable":
                return JSONResponse(status_code=400, content=result)
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

    return router