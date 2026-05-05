from __future__ import annotations

from typing import Any

from kn_graph.config import Settings
from kn_graph.services.workspace_layout_store import WorkspaceLayoutStore


class WorkspaceService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store: Any = None
        self._degraded_reason = ""

    def _ensure_store(self) -> Any:
        if self._store is not None:
            return self._store
        try:
            storage_path = self._settings.workspace_layouts_path
            self._store = WorkspaceLayoutStore(storage_path=storage_path)
        except Exception as exc:
            self._store = _InMemoryWorkspaceLayoutStore()
            self._degraded_reason = f"workspace_layout_store_load_failed:{exc}"
        return self._store

    def list_layouts(self) -> dict[str, Any]:
        store = self._ensure_store()
        payload = store.list_layouts()
        result = dict(payload) if isinstance(payload, dict) else {"layouts": payload if isinstance(payload, list) else []}
        if self._degraded_reason:
            result["degraded"] = True
            result["degraded_reason"] = self._degraded_reason
        return result

    def get_layout(self, name: str = "default") -> dict[str, Any] | None:
        store = self._ensure_store()
        payload = store.get_layout(name=name)
        if payload is None:
            return None
        result = dict(payload)
        if self._degraded_reason:
            result["degraded"] = True
            result["degraded_reason"] = self._degraded_reason
        return result

    def save_layout(self, name: str, layout: dict[str, Any]) -> dict[str, Any]:
        store = self._ensure_store()
        payload = store.save_layout(name=name, layout=layout)
        result = dict(payload)
        if self._degraded_reason:
            result["degraded"] = True
            result["degraded_reason"] = self._degraded_reason
        return result


class _InMemoryWorkspaceLayoutStore:
    def __init__(self) -> None:
        from datetime import datetime, timezone
        self._tz = timezone
        self._layouts: dict[str, dict[str, Any]] = {}

    def save_layout(self, name: str, layout: dict[str, Any]) -> dict[str, Any]:
        key = str(name or "default").strip() or "default"
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc).isoformat()
        row = {"name": key, "layout": dict(layout), "updated_at": now}
        self._layouts[key] = row
        return dict(row)

    def get_layout(self, name: str) -> dict[str, Any] | None:
        key = str(name or "default").strip() or "default"
        row = self._layouts.get(key)
        return dict(row) if isinstance(row, dict) else None

    def list_layouts(self) -> dict[str, Any]:
        rows = list(self._layouts.values())
        rows.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        return {"layouts": [{"name": str(r.get("name", "")), "updated_at": str(r.get("updated_at", ""))} for r in rows]}