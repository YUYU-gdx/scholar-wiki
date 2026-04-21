from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class WorkspaceLayoutStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._lock = Lock()
        self._storage_path = storage_path
        self._items: dict[str, dict[str, Any]] = {}
        self._storage_mode = "memory"
        self._degraded_reason = ""
        if storage_path is not None:
            self._storage_mode = "file"
            self._load_from_file()

    def _load_from_file(self) -> None:
        if self._storage_path is None:
            return
        try:
            if not self._storage_path.exists():
                return
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            items = payload.get("items", {})
            if not isinstance(items, dict):
                return
            normalized: dict[str, dict[str, Any]] = {}
            for name, item in items.items():
                if not isinstance(item, dict):
                    continue
                layout = item.get("layout")
                if not isinstance(layout, dict):
                    continue
                normalized[str(name)] = {
                    "layout": layout,
                    "updated_at": str(item.get("updated_at", "") or _now_iso()),
                }
            self._items = normalized
        except Exception as exc:
            self._storage_mode = "memory"
            self._degraded_reason = f"load_failed:{exc}"

    def _persist(self) -> None:
        if self._storage_path is None or self._storage_mode != "file":
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"items": self._items}
            self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._storage_mode = "memory"
            self._degraded_reason = f"persist_failed:{exc}"

    def list_layouts(self) -> dict[str, Any]:
        with self._lock:
            layouts = [
                {"name": name, "updated_at": str(item.get("updated_at", ""))}
                for name, item in sorted(self._items.items(), key=lambda x: x[0])
            ]
            return {
                "layouts": layouts,
                "storage_mode": self._storage_mode,
                "degraded": bool(self._degraded_reason),
                "degraded_reason": self._degraded_reason,
            }

    def get_layout(self, name: str = "default") -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(name)
            if item is None:
                return None
            return {
                "name": name,
                "layout": item.get("layout", {}),
                "updated_at": str(item.get("updated_at", "")),
                "storage_mode": self._storage_mode,
                "degraded": bool(self._degraded_reason),
                "degraded_reason": self._degraded_reason,
            }

    def save_layout(self, name: str, layout: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now = _now_iso()
            self._items[name] = {"layout": layout, "updated_at": now}
            self._persist()
            return {
                "name": name,
                "layout": layout,
                "updated_at": now,
                "storage_mode": self._storage_mode,
                "degraded": bool(self._degraded_reason),
                "degraded_reason": self._degraded_reason,
            }
