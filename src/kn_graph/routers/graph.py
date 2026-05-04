from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from kn_graph.services.graph_service import GraphService


def create_router(graph_service: GraphService) -> APIRouter:
    router = APIRouter(prefix="/graph", tags=["graph"])

    @router.get("/overview")
    async def graph_overview(library_id: str = Query(default="")):
        return graph_service.get_overview(library_id=library_id)

    @router.get("/full")
    async def graph_full(library_id: str = Query(default="")):
        return graph_service.get_full(library_id=library_id)

    @router.get("/search")
    async def graph_search(
        q: str = Query(default="", alias="q"),
        query: str = Query(default=""),
        mode: str = Query(default="variable"),
        limit: int = Query(default=20, alias="limit"),
        top_k: int = Query(default=20),
        keyword_weight: float = Query(default=0.5),
        vector_weight: float = Query(default=0.5),
        vector_backend: str = Query(default="hash"),
        library_id: str = Query(default=""),
    ):
        effective_query = query or q
        effective_limit = limit or top_k
        return graph_service.search(
            query=effective_query,
            mode=mode,
            limit=effective_limit,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
            vector_backend=vector_backend,
            library_id=library_id,
        )

    @router.get("/neighborhood")
    async def graph_neighborhood(
        node_id: str = Query(...),
        hops: int = Query(default=1),
        limit_nodes: int = Query(default=350),
        limit_edges: int = Query(default=900),
        library_id: str = Query(default=""),
    ):
        result = graph_service.get_neighborhood(
            node_id=node_id,
            hops=hops,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
            library_id=library_id,
        )
        if result is None:
            return JSONResponse(status_code=404, content={"error": "node_not_found", "node_id": node_id})
        return result

    @router.post("/reload")
    async def graph_reload(library_id: str = Query(default="")):
        return graph_service.reload(library_id=library_id)

    return router


def create_paper_router(graph_service: GraphService) -> APIRouter:
    router = APIRouter(tags=["graph"])

    @router.get("/paper/{paper_id_or_doi}")
    async def paper_detail(paper_id_or_doi: str, library_id: str = Query(default="")):
        result = graph_service.get_paper(paper_id_or_doi, library_id=library_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "paper_not_found", "paper_id": paper_id_or_doi})
        return result

    @router.get("/variable/{node_id}")
    async def variable_detail(node_id: str, library_id: str = Query(default="")):
        result = graph_service.get_variable(node_id, library_id=library_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "node_not_found", "node_id": node_id})
        return result

    @router.delete("/paper/{paper_id_or_doi}")
    async def delete_paper(paper_id_or_doi: str, library_id: str = Query(default="")):
        result = graph_service.delete_paper(paper_id_or_doi, library_id=library_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "paper_not_found", "paper_id": paper_id_or_doi})
        return result

    @router.get("/paper/{paper_id_or_doi}/files")
    async def paper_files(paper_id_or_doi: str, library_id: str = Query(default="")):
        result = graph_service.get_paper_files(paper_id_or_doi, library_id=library_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "paper_not_found", "paper_id": paper_id_or_doi})
        return result

    @router.get("/paper/{paper_id_or_doi}/content")
    async def paper_content(
        paper_id_or_doi: str,
        library_id: str = Query(default=""),
        type: str = Query(default=""),
    ):
        resolved = graph_service.resolve_paper_file(paper_id_or_doi, library_id=library_id, file_type=type)
        if resolved is None:
            return JSONResponse(status_code=404, content={"error": "paper_file_not_found", "paper_id": paper_id_or_doi})
        path = str(resolved.get("path", "")).strip()
        if not path:
            return JSONResponse(status_code=404, content={"error": "paper_file_not_found", "paper_id": paper_id_or_doi})
        try:
            p = Path(path)
            if not p.exists() or not p.is_file():
                return JSONResponse(status_code=404, content={"error": "paper_file_missing", "paper_id": paper_id_or_doi, "path": path})
            kind = str(resolved.get("type", "")).strip().lower()
            headers = {
                "X-KN-Absolute-Path": str(p.resolve()),
                "X-KN-File-Name": str(resolved.get("name", "") or p.name),
                "X-KN-File-Type": kind,
            }
            if kind == "pdf":
                data = p.read_bytes()
                is_valid = len(data) >= 5 and data[:5] == b"%PDF-"
                headers["X-KN-File-Valid"] = "1" if is_valid else "0"
                if not is_valid:
                    headers["X-KN-File-Reason"] = "invalid_pdf_header"
                return Response(content=data, media_type="application/pdf", headers=headers)
            text = p.read_text(encoding="utf-8", errors="replace")
            return Response(content=text, media_type="text/plain; charset=utf-8", headers=headers)
        except OSError as exc:
            return JSONResponse(status_code=500, content={"error": "paper_file_read_failed", "detail": str(exc)})

    @router.get("/paper/{paper_id_or_doi}/asset")
    async def paper_asset(
        paper_id_or_doi: str,
        library_id: str = Query(default=""),
        type: str = Query(default="markdown"),
        rel_path: str = Query(default=""),
    ):
        rel = str(rel_path or "").strip()
        if not rel:
            return JSONResponse(status_code=400, content={"error": "rel_path_required"})
        resolved = graph_service.resolve_paper_file(paper_id_or_doi, library_id=library_id, file_type=type)
        if resolved is None:
            return JSONResponse(status_code=404, content={"error": "paper_file_not_found", "paper_id": paper_id_or_doi})
        base_file = Path(str(resolved.get("path", "") or "")).resolve()
        base_dir = base_file.parent
        try:
            candidate = (base_dir / rel).resolve()
            base_dir_s = str(base_dir)
            candidate_s = str(candidate)
            if not (candidate_s == base_dir_s or candidate_s.startswith(base_dir_s + os.sep)):
                return JSONResponse(status_code=403, content={"error": "asset_path_forbidden"})
            if not candidate.exists() or not candidate.is_file():
                return JSONResponse(status_code=404, content={"error": "asset_not_found", "rel_path": rel})
            suffix = candidate.suffix.lower()
            media_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".svg": "image/svg+xml",
                ".bmp": "image/bmp",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".mjs": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".ttf": "font/ttf",
            }
            media = media_map.get(suffix, "application/octet-stream")
            return Response(content=candidate.read_bytes(), media_type=media)
        except OSError as exc:
            return JSONResponse(status_code=500, content={"error": "asset_read_failed", "detail": str(exc)})

    return router
