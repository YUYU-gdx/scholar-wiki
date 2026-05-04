from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from kn_graph.services.settings_service import SettingsService


def create_router(settings_service: SettingsService) -> APIRouter:
    router = APIRouter(prefix="/settings", tags=["settings"])

    @router.get("")
    async def get_settings():
        return settings_service.get_all()

    @router.get("/schema")
    async def get_settings_schema():
        return settings_service.get_schema()

    @router.put("/{category}")
    async def update_settings(category: str, body: dict[str, Any]):
        try:
            saved = settings_service.update_category(category, body)
            return {"ok": True, "category": category, "config": saved}
        except KeyError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=400, content={"error": "settings_update_failed", "detail": str(exc)})

    return router
