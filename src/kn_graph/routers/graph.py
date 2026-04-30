from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from kn_graph.services.graph_service import GraphService


def create_router(graph_service: GraphService) -> APIRouter:
    router = APIRouter(prefix="/graph", tags=["graph"])

    @router.get("/overview")
    async def graph_overview():
        return graph_service.get_overview()

    @router.get("/full")
    async def graph_full():
        return graph_service.get_full()

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
        )

    @router.get("/neighborhood")
    async def graph_neighborhood(
        node_id: str = Query(...),
        hops: int = Query(default=1),
        limit_nodes: int = Query(default=350),
        limit_edges: int = Query(default=900),
    ):
        result = graph_service.get_neighborhood(
            node_id=node_id,
            hops=hops,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
        if result is None:
            return JSONResponse(status_code=404, content={"error": "node_not_found", "node_id": node_id})
        return result

    return router


def create_paper_router(graph_service: GraphService) -> APIRouter:
    router = APIRouter(tags=["graph"])

    @router.get("/paper/{paper_id_or_doi}")
    async def paper_detail(paper_id_or_doi: str):
        result = graph_service.get_paper(paper_id_or_doi)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "paper_not_found", "paper_id": paper_id_or_doi})
        return result

    @router.get("/variable/{node_id}")
    async def variable_detail(node_id: str):
        result = graph_service.get_variable(node_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "node_not_found", "node_id": node_id})
        return result

    return router