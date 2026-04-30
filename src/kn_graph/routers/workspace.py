from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from kn_graph.services.workspace_service import WorkspaceService


def create_router(workspace_service: WorkspaceService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/workspace", tags=["workspace"])

    @router.get("/layouts")
    async def list_layouts():
        return workspace_service.list_layouts()

    @router.get("/layout")
    async def get_layout(name: str = Query(default="default")):
        result = workspace_service.get_layout(name=name)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "workspace_layout_not_found", "name": name})
        return result

    @router.post("/layout")
    async def save_layout(body: dict[str, Any]):
        name = str(body.get("name", "default") or "default").strip()
        if not name:
            return JSONResponse(status_code=400, content={"error": "name_required"})
        layout = body.get("layout")
        if not isinstance(layout, dict):
            return JSONResponse(status_code=400, content={"error": "layout_object_required"})
        return workspace_service.save_layout(name=name, layout=layout)

    return router