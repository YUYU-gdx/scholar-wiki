from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from kn_graph.models.literature import LiteratureAnswerRequest, LiteratureImportRequest
from kn_graph.services.literature_service import LiteratureService


def create_router(literature_service: LiteratureService) -> APIRouter:
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

    return router