from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, Response

from kn_graph.services.graph_service import GraphService
from kn_graph.services.workspace_paths import resolve_library_workspace
from kn_graph.services.variable_concept_index import VariableConceptIndexService


_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")


def _norm(text: str) -> str:
    return "_".join(_TOKEN_RE.findall(str(text or "").lower()))


def _pick_concept_from_variable_detail(payload: dict[str, Any]) -> str:
    groups = payload.get("paper_groups", []) if isinstance(payload, dict) else []
    if not isinstance(groups, list):
        return ""
    for group in groups:
        if not isinstance(group, dict):
            continue
        concepts = group.get("concepts", [])
        if not isinstance(concepts, list):
            continue
        for item in concepts:
            if not isinstance(item, dict):
                continue
            txt = str(item.get("definition", "") or "").strip()
            if txt:
                return txt
    return ""


def _resolve_node_id_by_variable_name(
    graph_service: GraphService,
    *,
    library_id: str,
    variable_name: str,
) -> str:
    result = graph_service.search(
        query=variable_name,
        mode="variable",
        limit=20,
        keyword_weight=0.4,
        vector_weight=0.6,
        vector_backend="hash",
        library_id=library_id,
    )
    rows = result.get("results", []) if isinstance(result, dict) else []
    if not isinstance(rows, list):
        return ""
    needle = _norm(variable_name)
    first_id = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        nid = str(row.get("id", "") or row.get("node_id", "") or "").strip()
        if not nid:
            continue
        if not first_id:
            first_id = nid
        title = str(row.get("title", "") or row.get("name", "") or "").strip()
        if _norm(title) == needle or _norm(nid.split("::")[-1]) == needle:
            return nid
    return first_id


def _library_workspace_path(graph_service: GraphService, library_id: str) -> Path:
    path = resolve_library_workspace(library_id, graph_service._settings.workspaces_dir, must_exist=False)
    if path is None:
        raise ValueError("library_id_invalid")
    return path


def _collect_neighbor_variables(
    graph_service: GraphService,
    *,
    library_id: str,
    variable_name: str,
    top_k: int,
) -> dict[str, Any]:
    node_id = _resolve_node_id_by_variable_name(
        graph_service,
        library_id=library_id,
        variable_name=variable_name,
    )
    if not node_id:
        return {"matched": None, "cause_variables": [], "effect_variables": []}
    neighborhood = graph_service.get_neighborhood(
        node_id=node_id,
        hops=1,
        limit_nodes=120,
        limit_edges=240,
        library_id=library_id,
    )
    if not isinstance(neighborhood, dict):
        return {"matched": None, "cause_variables": [], "effect_variables": []}
    nodes = neighborhood.get("nodes", [])
    edges = neighborhood.get("edges", [])
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    node_map: dict[str, dict[str, Any]] = {}
    for item in nodes:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id", "") or "").strip()
        if nid:
            node_map[nid] = item

    matched_detail = graph_service.get_variable(node_id, library_id=library_id)
    matched = {
        "node_id": node_id,
        "variable_name": str(node_map.get(node_id, {}).get("label", "") or node_map.get(node_id, {}).get("name", "") or node_id),
        "concept_text": _pick_concept_from_variable_detail(matched_detail or {}),
        "library_id": library_id,
    }

    cause_ids: list[str] = []
    effect_ids: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source", "") or edge.get("source_node_id", "") or "").strip()
        tgt = str(edge.get("target", "") or edge.get("target_node_id", "") or "").strip()
        if src == node_id and tgt and tgt in node_map:
            effect_ids.append(tgt)
        elif tgt == node_id and src and src in node_map:
            cause_ids.append(src)

    def _to_min_rows(ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for nid in ids:
            if nid in seen:
                continue
            seen.add(nid)
            n = node_map.get(nid, {})
            if str(n.get("type", "") or "").strip() not in {"variable", ""}:
                continue
            detail = graph_service.get_variable(nid, library_id=library_id)
            out.append(
                {
                    "node_id": nid,
                    "variable_name": str(n.get("label", "") or n.get("name", "") or nid),
                    "concept_text": _pick_concept_from_variable_detail(detail or {}),
                    "library_id": library_id,
                }
            )
            if len(out) >= top_k:
                break
        return out

    return {
        "matched": matched,
        "cause_variables": _to_min_rows(cause_ids),
        "effect_variables": _to_min_rows(effect_ids),
    }


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

    @router.post("/semantic-variables/search")
    async def semantic_variable_search(
        payload: dict[str, Any] = Body(default={}),
    ):
        query = str(payload.get("query", "") or "").strip()
        if not query:
            return JSONResponse(status_code=400, content={"error": "query_required"})
        raw_top_k = int(payload.get("top_k", 5) or 5)
        top_k = min(20, max(3, raw_top_k))
        raw_libs = payload.get("library_ids", [])
        library_ids = [str(x or "").strip() for x in (raw_libs if isinstance(raw_libs, list) else []) if str(x or "").strip()]
        if not library_ids:
            return JSONResponse(status_code=400, content={"error": "library_ids_required"})

        matched_variables: list[dict[str, Any]] = []
        for lib in library_ids:
            workspace = _library_workspace_path(graph_service, lib)
            service = VariableConceptIndexService(workspace_path=str(workspace))
            try:
                hits = service.query(library_id=lib, query=query, top_k=top_k)
            except Exception as exc:
                return JSONResponse(status_code=500, content={"error": "semantic_search_failed", "library_id": lib, "detail": str(exc)})
            for hit in hits:
                variable_name = str(hit.get("variable_name", "") or "").strip()
                node_id = _resolve_node_id_by_variable_name(
                    graph_service,
                    library_id=lib,
                    variable_name=variable_name,
                ) if variable_name else ""
                matched_variables.append(
                    {
                        "id": str(hit.get("id", "") or ""),
                        "score": float(hit.get("score", 0.0) or 0.0),
                        "library_id": str(hit.get("library_id", "") or lib),
                        "paper_id": str(hit.get("paper_id", "") or ""),
                        "variable_name": variable_name,
                        "canonical_var_id": str(hit.get("canonical_var_id", "") or ""),
                        "concept_text": str(hit.get("concept_text", "") or ""),
                        "node_id": node_id,
                    }
                )

        matched_variables.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return {
            "ok": True,
            "query": query,
            "top_k": top_k,
            "library_ids": library_ids,
            "matched_variables": matched_variables[: max(top_k * max(1, len(library_ids)), top_k)],
        }

    @router.post("/semantic-variables/neighbors")
    async def semantic_variable_neighbors(
        payload: dict[str, Any] = Body(default={}),
    ):
        variable_name = str(payload.get("variable_name", "") or "").strip()
        if not variable_name:
            return JSONResponse(status_code=400, content={"error": "variable_name_required"})
        raw_top_k = int(payload.get("top_k", 5) or 5)
        top_k = min(20, max(3, raw_top_k))
        raw_libs = payload.get("library_ids", [])
        library_ids = [str(x or "").strip() for x in (raw_libs if isinstance(raw_libs, list) else []) if str(x or "").strip()]
        if not library_ids:
            return JSONResponse(status_code=400, content={"error": "library_ids_required"})

        rows: list[dict[str, Any]] = []
        for lib in library_ids:
            try:
                rows.append(
                    {
                        "library_id": lib,
                        **_collect_neighbor_variables(
                            graph_service,
                            library_id=lib,
                            variable_name=variable_name,
                            top_k=top_k,
                        ),
                    }
                )
            except Exception as exc:
                return JSONResponse(status_code=500, content={"error": "neighbor_search_failed", "library_id": lib, "detail": str(exc)})
        return {
            "ok": True,
            "variable_name": variable_name,
            "top_k": top_k,
            "library_ids": library_ids,
            "results": rows,
        }

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
