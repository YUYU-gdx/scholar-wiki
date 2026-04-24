from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_library_id(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", str(raw or "").strip())


def _safe_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(fallback)
    return payload if isinstance(payload, dict) else dict(fallback)


def registry_path_from_env() -> Path:
    raw = os.getenv("LITERATURE_LIBRARY_REGISTRY_PATH", "outputs/libraries/registry.json").strip() or "outputs/libraries/registry.json"
    return Path(raw)


def legacy_index_root_from_env() -> Path:
    raw = os.getenv("LITERATURE_LIBRARY_INDEX_ROOT", "outputs/literature_libraries").strip() or "outputs/literature_libraries"
    return Path(raw)


def workspace_root_base_from_env() -> Path:
    raw = os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", "").strip()
    if raw:
        return Path(raw)
    return (Path.home() / ".kn_graph" / "libraries" / "workspaces")


def _legacy_workspace_root_default() -> Path:
    return (Path(__file__).resolve().parents[2] / "outputs" / "libraries" / "workspaces").resolve()


def load_registry(path: Path) -> dict[str, Any]:
    fallback = {"version": 1, "updated_at": "", "default_library_id": "", "libraries": []}
    payload = _safe_json(path, fallback)
    libs = payload.get("libraries", [])
    if not isinstance(libs, list):
        libs = []
    cleaned: list[dict[str, Any]] = []
    for item in libs:
        if not isinstance(item, dict):
            continue
        library_id = _safe_library_id(str(item.get("library_id", "") or ""))
        if not library_id:
            continue
        cleaned.append(
            {
                "library_id": library_id,
                "workspace_root": str(item.get("workspace_root", "") or "").strip(),
                "index_path": str(item.get("index_path", "") or "").strip(),
                "paper_count": int(item.get("paper_count", 0) or 0),
                "updated_at": str(item.get("updated_at", "") or "").strip(),
                "state": str(item.get("state", "active") or "active").strip() or "active",
            }
        )
    payload["libraries"] = cleaned
    payload["version"] = int(payload.get("version", 1) or 1)
    payload["updated_at"] = str(payload.get("updated_at", "") or "")
    payload["default_library_id"] = _safe_library_id(str(payload.get("default_library_id", "") or ""))
    return payload


def save_registry(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = _now_iso()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def ensure_registry(registry_path: Path | None = None, legacy_index_root: Path | None = None) -> dict[str, Any]:
    reg_path = (registry_path or registry_path_from_env()).resolve()
    idx_root = (legacy_index_root or legacy_index_root_from_env()).resolve()
    workspace_base = workspace_root_base_from_env().resolve()
    workspace_base.mkdir(parents=True, exist_ok=True)
    migrate_legacy_workspace = not str(os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", "") or "").strip()
    legacy_workspace_root = _legacy_workspace_root_default()

    existing = load_registry(reg_path) if reg_path.exists() else {"version": 1, "updated_at": "", "default_library_id": "", "libraries": []}
    by_id = {str(item.get("library_id", "")): dict(item) for item in existing.get("libraries", []) if isinstance(item, dict)}

    if idx_root.exists() and idx_root.is_dir():
        for fp in sorted(idx_root.glob("*.json")):
            try:
                payload = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            library_id = _safe_library_id(str(payload.get("library_id", "") or fp.stem))
            if not library_id:
                continue
            raw_workspace = (
                str(payload.get("workspace_root", "") or "").strip()
                or str(payload.get("workspace_path", "") or "").strip()
                or str(payload.get("library_root", "") or "").strip()
                or str(payload.get("root_path", "") or "").strip()
            )
            workspace_root = Path(raw_workspace).resolve() if raw_workspace else (workspace_base / library_id).resolve()
            workspace_root.mkdir(parents=True, exist_ok=True)
            paper_count_raw = payload.get("paper_count", 0)
            try:
                paper_count = max(0, int(paper_count_raw))
            except Exception:
                paper_ids = payload.get("paper_ids", [])
                paper_count = len(paper_ids) if isinstance(paper_ids, list) else 0
            prev = by_id.get(library_id, {})
            by_id[library_id] = {
                "library_id": library_id,
                "workspace_root": str(workspace_root),
                "index_path": str(fp.resolve()),
                "paper_count": paper_count,
                "updated_at": str(payload.get("updated_at", "") or prev.get("updated_at", "") or ""),
                "state": str(prev.get("state", "active") or "active"),
            }

    # Self-heal existing registry rows that may miss workspace_root from older versions.
    for lib_id, item in list(by_id.items()):
        if not isinstance(item, dict):
            continue
        root = str(item.get("workspace_root", "") or "").strip()
        if root:
            if migrate_legacy_workspace:
                try:
                    root_path = Path(root).resolve()
                    in_legacy = root_path == legacy_workspace_root or legacy_workspace_root in root_path.parents
                    if in_legacy:
                        new_root = (workspace_base / str(lib_id)).resolve()
                        if root_path != new_root:
                            new_root.parent.mkdir(parents=True, exist_ok=True)
                            if root_path.exists() and root_path.is_dir() and not new_root.exists():
                                shutil.move(str(root_path), str(new_root))
                            else:
                                new_root.mkdir(parents=True, exist_ok=True)
                            item["workspace_root"] = str(new_root)
                except Exception:
                    pass
            continue
        fallback_root = (workspace_base / str(lib_id)).resolve()
        fallback_root.mkdir(parents=True, exist_ok=True)
        item["workspace_root"] = str(fallback_root)
        item["state"] = str(item.get("state", "active") or "active")
        by_id[lib_id] = item

    rows = list(by_id.values())
    rows.sort(key=lambda x: (str(x.get("updated_at", "")), str(x.get("library_id", ""))), reverse=True)
    default_library_id = _safe_library_id(str(existing.get("default_library_id", "") or os.getenv("LITERATURE_DEFAULT_LIBRARY_ID", "") or ""))
    if not default_library_id and rows:
        default_library_id = str(rows[0].get("library_id", "") or "")
    snapshot = {
        "version": 1,
        "default_library_id": default_library_id,
        "libraries": rows,
        "updated_at": _now_iso(),
    }
    return save_registry(reg_path, snapshot)


def list_libraries_payload(registry: dict[str, Any]) -> dict[str, Any]:
    rows = registry.get("libraries", []) if isinstance(registry, dict) else []
    if not isinstance(rows, list):
        rows = []
    libraries: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        libraries.append(
            {
                "library_id": str(item.get("library_id", "") or "").strip(),
                "paper_count": max(0, int(item.get("paper_count", 0) or 0)),
                "updated_at": str(item.get("updated_at", "") or "").strip(),
                "path": str(item.get("index_path", "") or "").strip(),
                "workspace_path": str(item.get("workspace_root", "") or "").strip(),
            }
        )
    return {
        "libraries": libraries,
        "default_library_id": str(registry.get("default_library_id", "") or "").strip(),
    }


def resolve_workspace_root(registry: dict[str, Any], library_id: str) -> str:
    target = _safe_library_id(library_id)
    if not target:
        return ""
    for item in registry.get("libraries", []) if isinstance(registry, dict) else []:
        if not isinstance(item, dict):
            continue
        if _safe_library_id(str(item.get("library_id", "") or "")) != target:
            continue
        root = str(item.get("workspace_root", "") or "").strip()
        if not root:
            return ""
        try:
            return str(Path(root).resolve())
        except Exception:
            return root
    return ""
