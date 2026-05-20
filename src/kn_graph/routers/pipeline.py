from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from kn_graph.services.pipeline_service import PipelineService
from kn_graph.services import pipeline_runtime
from kn_graph.services.file_access_diagnostics import build_import_path_diagnostics, write_import_path_diagnostics_log
from kn_graph.services.workspace_paths import resolve_library_workspace

_ALLOWED_UPLOAD_EXTS = {".pdf", ".docx", ".md", ".html"}
logger = logging.getLogger(__name__)


def _resolve_library_workspace(library_id: str, workspaces_dir: Path) -> Path:
    target = resolve_library_workspace(library_id, workspaces_dir, create=True, must_exist=True)
    if target is None:
        raise RuntimeError(f"library_workspace_invalid:{library_id}")
    # Auto-create workspace directory for existing library ids to avoid
    # import hard-fail after reinstall/path migration.
    if not target.is_dir():
        raise RuntimeError(f"library_workspace_invalid:{library_id}")
    return target


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


def _copy_file_with_hash(source: Path, target: Path) -> tuple[str, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    size = 0
    with source.open("rb") as src, target.open("wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _find_duplicate_pdf_by_hash(workspace_root: Path, upload_hash: str) -> dict[str, str] | None:
    db_path = workspace_root / "kn_gragh.db"
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT paper_id, title, source_pdf_path FROM papers").fetchall()
        finally:
            conn.close()
    except Exception:
        return None
    for row in rows:
        src_pdf = Path(str(row["source_pdf_path"] or "").strip())
        if not src_pdf.is_file():
            continue
        try:
            if _sha256_file(src_pdf) == upload_hash:
                return {
                    "paper_id": str(row["paper_id"] or "").strip(),
                    "title": str(row["title"] or "").strip(),
                    "source_pdf_path": str(src_pdf.resolve()),
                }
        except Exception:
            continue
    return None


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_RETRY_SETTINGS_OPTION_KEYS = {
    "mineru_api_key",
    "extraction_mode",
    "pipeline_agent_backend",
    "pipeline_agent_provider",
    "pipeline_agent_model",
    "pipeline_agent_api_key",
    "pipeline_agent_base_url",
    "pipeline_agent_reasoning_effort",
}


def _drop_retry_settings_overrides(options: dict[str, Any]) -> dict[str, Any]:
    """Remove persisted Settings-derived options so retry uses current Settings values."""
    out = dict(options)
    for key in _RETRY_SETTINGS_OPTION_KEYS:
        out.pop(key, None)
    return out


def create_router(pipeline_service: PipelineService) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["pipeline"])

    async def _retry_job_impl(job_id: str):
        result = pipeline_service.retry_job(job_id)
        if result is None:
            row = pipeline_service.get_job(job_id)
            if row is None:
                return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})

            run_dir = pipeline_service.resolve_run_dir(row)
            source_path = pipeline_service.resolve_retry_source_pdf(row)
            if source_path is None:
                return JSONResponse(status_code=404, content={"error": "retry_source_pdf_missing", "job_id": job_id})
            source_path = source_path.resolve()
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
            parsed_options = _drop_retry_settings_overrides(parsed_options)
            if run_dir is not None:
                parsed_options["_job_root"] = str(run_dir.parent.resolve())
            else:
                parsed_options.pop("_job_root", None)
            parsed_options.pop("_workspace_path", None)
            parsed_options["library_id"] = lib
            pipeline_service.update_job(
                job_id,
                {
                    "status": "running",
                    "stage": "accepted",
                    "error_code": "",
                    "error_detail": "",
                    "progress": 0,
                    "input_path": str(source_path),
                    "file_name": source_path.name,
                    "last_event": "retry_resume",
                    "requested_cancel": False,
                },
            )
            pipeline_runtime.dispatch_inline(
                pipeline_service.store,
                job_id,
                str(source_path),
                parsed_options,
                pipeline_service.runs_root,
            )
            return JSONResponse(status_code=202, content={"job_id": job_id, "resumed": True, "retry_mode": "resume"})
        if isinstance(result, dict) and "error" in result and result.get("error") == "job_not_retryable":
            return JSONResponse(status_code=400, content=result)
        return result

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
        ext = Path(str(file.filename)).suffix.lower()
        if ext not in _ALLOWED_UPLOAD_EXTS:
            return JSONResponse(
                status_code=400,
                content={"error": "unsupported_file_type", "allowed_extensions": sorted(_ALLOWED_UPLOAD_EXTS)},
            )

        try:
            workspace_root = _resolve_library_workspace(lib, pipeline_service._settings.workspaces_dir)
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
        duplicate = _find_duplicate_pdf_by_hash(workspace_root, file_hash)
        if isinstance(duplicate, dict):
            try:
                input_path.unlink(missing_ok=True)
            except Exception:
                pass
            return JSONResponse(
                status_code=400,
                content={
                    "error": "duplicate_pdf_in_library",
                    "message": "已有相同文献",
                    "library_id": lib,
                    "file_name": upload_name,
                    "existing_paper": duplicate,
                },
            )
        path_diag = build_import_path_diagnostics(
            data_dir=getattr(pipeline_service._settings, "data_dir", ""),
            workspaces_dir=getattr(pipeline_service._settings, "workspaces_dir", ""),
            library_id=lib,
            workspace_path=workspace_root,
            runs_root=runs_root,
            run_dir=run_dir,
            input_path=input_path,
        )
        logger.warning("pipeline_import_path_diagnostics %s", json.dumps(path_diag, ensure_ascii=False))
        write_import_path_diagnostics_log(
            data_dir=getattr(pipeline_service._settings, "data_dir", ""),
            event="pipeline_import_path_diagnostics",
            payload=path_diag,
        )
        parsed_options["_path_diagnostics"] = path_diag
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
            "result_json": _safe_json_dumps({"path_diagnostics": path_diag}),
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
                    payload = body
                elif isinstance(body, (bytes, bytearray)):
                    payload = json.loads(body.decode("utf-8"))
                elif isinstance(body, str):
                    payload = json.loads(body)
                else:
                    payload = {"file_name": str(getattr(f, "filename", "") or "")}

                status_code = int(getattr(result, "status_code", 500) or 500)
                has_job_id = bool(str(payload.get("job_id", "") or "").strip()) if isinstance(payload, dict) else False
                if status_code == 202 and has_job_id and isinstance(payload, dict):
                    accepted.append(payload)
                else:
                    err = ""
                    if isinstance(payload, dict):
                        err = str(payload.get("error", "") or "").strip()
                    rejected.append(
                        {
                            "file_name": str(getattr(f, "filename", "") or ""),
                            "error": err or f"submit_failed_http_{status_code}",
                            "detail": payload if isinstance(payload, dict) else {},
                        }
                    )
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

    @router.post("/pipeline/parse-extract/path-batch")
    async def create_parse_extract_path_batch(payload: dict[str, Any] = Body(default={})):
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list) or not items:
            return JSONResponse(status_code=400, content={"error": "items_required"})
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                rejected.append({"error": "invalid_item"})
                continue
            lib = str(raw.get("library_id", "") or "").strip()
            pdf_path_raw = str(raw.get("pdf_path", "") or "").strip()
            options_obj = raw.get("options", {})
            if not lib:
                rejected.append({"library_id": lib, "pdf_path": pdf_path_raw, "error": "library_id_required"})
                continue
            if not pdf_path_raw:
                rejected.append({"library_id": lib, "pdf_path": pdf_path_raw, "error": "pdf_path_required"})
                continue
            src = Path(pdf_path_raw).expanduser().resolve()
            if not src.is_file():
                rejected.append({"library_id": lib, "pdf_path": pdf_path_raw, "error": "pdf_not_found"})
                continue
            ext = src.suffix.lower()
            if ext not in _ALLOWED_UPLOAD_EXTS:
                rejected.append(
                    {
                        "library_id": lib,
                        "pdf_path": pdf_path_raw,
                        "error": "unsupported_file_type",
                        "allowed_extensions": sorted(_ALLOWED_UPLOAD_EXTS),
                    }
                )
                continue
            if not isinstance(options_obj, dict):
                rejected.append({"library_id": lib, "pdf_path": pdf_path_raw, "error": "options_must_be_object"})
                continue
            try:
                workspace_root = _resolve_library_workspace(lib, pipeline_service._settings.workspaces_dir)
            except Exception as exc:
                rejected.append(
                    {"library_id": lib, "pdf_path": pdf_path_raw, "error": "library_workspace_missing", "detail": str(exc)}
                )
                continue

            parsed_options = dict(options_obj)
            parsed_options["library_id"] = lib
            parsed_options["_workspace_path"] = str(workspace_root.resolve())

            job_id = f"job_{uuid.uuid4().hex}"
            runs_root = Path(str(getattr(pipeline_service, "_runs_root", workspace_root / "runs")))
            run_dir = runs_root / job_id
            input_path = run_dir / "input" / src.name
            parsed_options["_job_root"] = str(run_dir.resolve())
            try:
                file_hash, file_size = _copy_file_with_hash(src, input_path)
            except Exception as exc:
                rejected.append({"library_id": lib, "pdf_path": pdf_path_raw, "error": "copy_failed", "detail": str(exc)})
                continue

            duplicate = _find_duplicate_pdf_by_hash(workspace_root, file_hash)
            if isinstance(duplicate, dict):
                try:
                    input_path.unlink(missing_ok=True)
                except Exception:
                    pass
                rejected.append(
                    {
                        "library_id": lib,
                        "pdf_path": pdf_path_raw,
                        "file_name": src.name,
                        "error": "duplicate_pdf_in_library",
                        "message": "已有相同文献",
                        "existing_paper": duplicate,
                    }
                )
                continue

            path_diag = build_import_path_diagnostics(
                data_dir=getattr(pipeline_service._settings, "data_dir", ""),
                workspaces_dir=getattr(pipeline_service._settings, "workspaces_dir", ""),
                library_id=lib,
                workspace_path=workspace_root,
                runs_root=runs_root,
                run_dir=run_dir,
                input_path=input_path,
            )
            parsed_options["_path_diagnostics"] = path_diag
            idempotency_key = hashlib.sha256((file_hash + ":" + _safe_json_dumps(parsed_options)).encode("utf-8")).hexdigest()
            now = _now_iso()
            job_payload = {
                "job_id": job_id,
                "status": "queued",
                "stage": "accepted",
                "progress": 0,
                "error_code": "",
                "error_detail": "",
                "input_path": str(input_path),
                "output_path": "",
                "options_json": _safe_json_dumps(parsed_options),
                "result_json": _safe_json_dumps({"path_diagnostics": path_diag}),
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
                "file_name": src.name,
            }
            pipeline_service.create_job(job_payload)
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
            accepted.append(
                {
                    "job_id": job_id,
                    "status": "queued",
                    "library_id": lib,
                    "workspace_path": str(workspace_root.resolve()),
                    "file_name": src.name,
                    "sse_url": f"/v1/jobs/{job_id}/events",
                    "result_url": f"/v1/jobs/{job_id}/result",
                }
            )
        return JSONResponse(
            status_code=202 if accepted else 400,
            content={
                "accepted_count": len(accepted),
                "rejected_count": len(rejected),
                "accepted": accepted,
                "rejected": rejected,
            },
        )

    @router.post("/jobs/batch-status")
    async def batch_job_status(payload: dict[str, Any] = Body(default={})):
        job_ids = payload.get("job_ids", []) if isinstance(payload, dict) else []
        if not isinstance(job_ids, list) or not job_ids:
            return JSONResponse(status_code=400, content={"error": "job_ids_required"})
        out: list[dict[str, Any]] = []
        for raw_id in job_ids:
            job_id = str(raw_id or "").strip()
            if not job_id:
                continue
            row = pipeline_service.get_job(job_id)
            if row is None:
                out.append({"job_id": job_id, "error": "job_not_found"})
            else:
                out.append(row)
        return {"total": len(out), "jobs": out}

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
        return await _retry_job_impl(job_id)

    @router.delete("/jobs/{job_id}")
    async def delete_job(job_id: str):
        result = pipeline_service.delete_job(job_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "job_not_found", "job_id": job_id})
        return result

    @router.post("/jobs/batch")
    async def batch_jobs(action: str = Form(...), job_ids: str = Form(...)):
        try:
            parsed = json.loads(job_ids)
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"error": "invalid_job_ids_json"})
        if not isinstance(parsed, list):
            return JSONResponse(status_code=400, content={"error": "job_ids_must_be_array"})
        op = str(action or "").strip().lower()
        clean_ids = [str(x or "").strip() for x in parsed if str(x or "").strip()]
        if op not in {"cancel", "retry", "delete"}:
            return JSONResponse(status_code=400, content={"error": "invalid_action", "action": op})
        if not clean_ids:
            return JSONResponse(status_code=400, content={"error": "job_ids_required"})

        results: list[dict[str, Any]] = []
        success_count = 0
        for job_id in clean_ids:
            if op == "cancel":
                item = pipeline_service.cancel_job(job_id)
                ok = isinstance(item, dict) and "error" not in item
                payload = item if isinstance(item, dict) else {"job_id": job_id}
            elif op == "delete":
                item = pipeline_service.delete_job(job_id)
                ok = isinstance(item, dict) and "error" not in item
                payload = item if isinstance(item, dict) else {"error": "job_not_found", "job_id": job_id}
            else:
                resp = await _retry_job_impl(job_id)
                status_code = int(getattr(resp, "status_code", 200) or 200) if hasattr(resp, "status_code") else 200
                body = getattr(resp, "body", resp)
                if isinstance(body, (bytes, bytearray)):
                    payload = json.loads(body.decode("utf-8"))
                elif isinstance(body, str):
                    payload = json.loads(body)
                elif isinstance(body, dict):
                    payload = body
                else:
                    payload = {"job_id": job_id}
                ok = status_code < 400 and "error" not in payload
            payload["action"] = op
            results.append(payload)
            if ok:
                success_count += 1

        out = {
            "action": op,
            "total": len(clean_ids),
            "success_count": success_count,
            "failure_count": len(clean_ids) - success_count,
            "results": results,
        }
        if out["failure_count"] > 0:
            return JSONResponse(status_code=207, content=out)
        return out

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

