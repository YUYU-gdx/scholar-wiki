from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from kn_graph.models.literature import (
    LiteratureAnswerRequest, LiteratureCreateLibraryRequest, LiteratureImportRequest,
    ZoteroScanRequest, ZoteroImportRequest,
)
from kn_graph.services.literature_service import LiteratureService


def create_router(literature_service: LiteratureService, pipeline_service: Any = None) -> APIRouter:
    router = APIRouter(prefix="/literature", tags=["literature"])

    @router.get("/search")
    async def literature_search(
        q: str = Query(default="", alias="q"),
        query: str = Query(default=""),
        top_k: int = Query(default=20),
        limit: int = Query(default=20),
        levels: str = Query(default="sentence"),
        library_id: str = Query(default=""),
        keyword_weight: float = Query(default=0.4),
        rag_weight: float = Query(default=0.6),
        include_expanded_context: bool = Query(default=True),
    ):
        effective_query = query or q
        if not effective_query:
            return JSONResponse(status_code=400, content={"error": "query_required"})
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        parsed_levels = [x.strip().lower() for x in levels.split(",") if x.strip()] if levels else ["sentence"]
        effective_limit = top_k or limit
        return literature_service.search(
            query=effective_query,
            top_k=effective_limit,
            levels=parsed_levels,
            library_id=library_id,
            keyword_weight=keyword_weight,
            rag_weight=rag_weight,
            include_expanded_context=include_expanded_context,
        )

    @router.get("/libraries")
    async def list_libraries():
        return literature_service.list_libraries()

    @router.post("/libraries")
    async def create_library(body: LiteratureCreateLibraryRequest):
        library_id = str(body.library_id or "").strip()
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        try:
            return literature_service.create_library(
                library_id=library_id,
                workspace_root=str(body.workspace_root or "").strip(),
                set_default=bool(body.set_default),
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "library_create_failed", "detail": str(exc)})

    @router.delete("/libraries/{library_id}")
    async def delete_library(
        library_id: str,
        delete_workspace_data: bool = Query(default=True),
    ):
        lib = str(library_id or "").strip()
        if not lib:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        try:
            result = literature_service.delete_library(
                library_id=lib,
                delete_workspace_data=bool(delete_workspace_data),
            )
            if not bool(result.get("deleted", False)):
                return JSONResponse(status_code=404, content={"error": "library_not_found", "library_id": lib})
            return result
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "library_delete_failed", "detail": str(exc)})

    @router.post("/import")
    async def import_manifest(body: LiteratureImportRequest):
        manifest_path = str(body.manifest_path or "").strip()
        if not manifest_path:
            return JSONResponse(status_code=400, content={"error": "manifest_path_required"})
        library_id = str(body.library_id or "").strip()
        options = dict(body.options) if body.options else {}
        if library_id and "library_id" not in options:
            options["library_id"] = library_id
        try:
            result = literature_service.import_manifest(manifest_path=manifest_path, options=options)
            return result
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "literature_import_failed", "detail": str(exc)})

    @router.post("/answer")
    async def literature_answer(body: LiteratureAnswerRequest):
        query = str(body.query or "").strip()
        if not query:
            return JSONResponse(status_code=400, content={"error": "query_required"})
        library_id = str(body.library_id or "").strip()
        if not library_id:
            return JSONResponse(status_code=400, content={"error": "library_id_required"})
        parsed_levels = body.levels if body.levels else ["sentence"]
        try:
            result = literature_service.answer(
                query=query,
                top_k=body.top_k,
                levels=parsed_levels,
                library_id=library_id,
                keyword_weight=body.keyword_weight,
                rag_weight=body.rag_weight,
            )
            return result
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "literature_answer_failed", "detail": str(exc)})

    @router.post("/zotero/scan")
    async def zotero_scan(body: ZoteroScanRequest):
        data_dir = str(body.data_dir or "").strip()
        if not data_dir:
            from kn_graph.services.zotero_scanner import _find_data_dir
            data_dir = _find_data_dir() or ""
        if not data_dir:
            return JSONResponse(status_code=400, content={"error": "data_dir_required",
                "hint": "Please provide the Zotero data directory path"})
        try:
            from kn_graph.services.zotero_scanner import scan_zotero
            result = scan_zotero(data_dir)
            return result
        except FileNotFoundError as exc:
            return JSONResponse(status_code=400, content={"error": "zotero_db_not_found", "detail": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "zotero_scan_failed", "detail": str(exc)})

    @router.post("/zotero/import")
    async def zotero_import(body: ZoteroImportRequest):
        try:
            import uuid, hashlib, json, shutil, os
            from pathlib import Path
            from kn_graph.services.zotero_scanner import get_zotero_items_batch
            from kn_graph.services.pipeline_runtime import dispatch_inline

            data_dir = str(body.data_dir or "").strip()
            library_id = str(body.library_id or "").strip()
            item_ids = list(body.item_ids or [])

            if not data_dir:
                from kn_graph.services.zotero_scanner import _find_data_dir
                data_dir = _find_data_dir() or ""
            if not data_dir:
                return JSONResponse(status_code=400, content={"error": "data_dir_required"})
            if not library_id:
                return JSONResponse(status_code=400, content={"error": "library_id_required"})
            if not item_ids:
                return JSONResponse(status_code=400, content={"error": "item_ids_required"})
            if pipeline_service is None:
                return JSONResponse(status_code=500, content={"error": "pipeline_service_unavailable"})

            # Resolve workspace path
            workspaces_dir = Path(literature_service._settings.workspaces_dir)
            workspace_path = workspaces_dir / library_id
            if not workspace_path.is_dir():
                return JSONResponse(status_code=400, content={"error": "workspace_not_found", "library_id": library_id})

            # Resolve runs root from settings
            settings_obj = literature_service._settings
            runs_root = Path(getattr(settings_obj, 'pipeline_runs_root',
                              os.path.join(getattr(settings_obj, 'data_dir', 'outputs'), 'runs')))

            job_ids = []
            all_items = get_zotero_items_batch(data_dir, item_ids)
            for zotero_data in all_items:

                # Find first PDF path that exists
                pdf_paths = [a for a in zotero_data.get("pdf_paths", []) if a.get("file_exists")]
                if not pdf_paths:
                    continue

                src_pdf = pdf_paths[0]["resolved_path"]
                job_id = f"job_{uuid.uuid4().hex}"
                run_dir = runs_root / job_id
                input_dir = run_dir / "input"
                input_dir.mkdir(parents=True, exist_ok=True)

                dest_pdf = input_dir / "upload.pdf"
                shutil.copy2(src_pdf, dest_pdf)

                file_size = os.path.getsize(dest_pdf)
                with open(dest_pdf, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()

                # Build Zotero options for the pipeline runtime
                zotero_options = {
                    "extraction_mode": "agent",
                    "library_id": library_id,
                    "_workspace_path": str(workspace_path),
                    "zotero_metadata": zotero_data.get("metadata", {}),
                    "zotero_creators": zotero_data.get("creators", []),
                    "zotero_notes": zotero_data.get("notes", []),
                    "zotero_annotations": zotero_data.get("annotations", []),
                    "_zotero_source": True,
                }

                file_name = os.path.basename(src_pdf)
                payload = {
                    "job_id": job_id,
                    "status": "queued",
                    "stage": "accepted",
                    "progress": 0,
                    "error_code": "",
                    "error_detail": "",
                    "input_path": str(dest_pdf),
                    "output_path": "",
                    "options_json": json.dumps(zotero_options, ensure_ascii=False),
                    "result_json": "{}",
                    "requested_cancel": False,
                    "idempotency_key": "",
                    "last_event": "accepted",
                    "file_size": file_size,
                    "file_hash": file_hash,
                    "library_id": library_id,
                    "workspace_path": str(workspace_path),
                    "source_job_id": "",
                    "file_name": file_name,
                }
                pipeline_service.create_job(payload)

                # Dispatch inline execution
                dispatch_inline(pipeline_service._store, job_id, str(dest_pdf), zotero_options, runs_root)

                job_ids.append(job_id)

            return {"job_ids": job_ids, "count": len(job_ids)}

        except Exception as exc:
            import traceback
            return JSONResponse(
                status_code=500,
                content={"error": "zotero_import_failed", "detail": str(exc), "traceback": traceback.format_exc()},
            )

    return router
