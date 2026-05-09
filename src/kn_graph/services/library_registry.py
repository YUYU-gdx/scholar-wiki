from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from kn_graph.core.runtime import resolve_storage_root

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_library_id(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    # Keep CJK, letters, digits, dot/underscore/hyphen; collapse other chars to underscore.
    cleaned = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9._-]+", "_", text)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned


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


def _default_workspace_root_base() -> Path:
    kn_graph_data = os.getenv("KN_GRAPH_DATA_DIR", "").strip()
    if kn_graph_data:
        return Path(kn_graph_data) / "libraries" / "workspaces"
    return resolve_storage_root(require_initialized=False) / "libraries" / "workspaces"


def workspace_root_base_from_env() -> Path:
    raw = os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", "").strip()
    if raw:
        return Path(raw)
    return _default_workspace_root_base()


_configured_paths: dict[str, Path] = {}


def configure(*, workspace_root: Path | None = None, registry_path: Path | None = None, index_root: Path | None = None) -> None:
    if workspace_root is not None:
        _configured_paths["workspace_root"] = workspace_root
    if registry_path is not None:
        _configured_paths["registry_path"] = registry_path
    if index_root is not None:
        _configured_paths["index_root"] = index_root


def _get_configured_workspace_root() -> Path | None:
    return _configured_paths.get("workspace_root")


def _legacy_workspace_root_default() -> Path:
    return (Path(__file__).resolve().parents[2] / "outputs" / "libraries" / "workspaces").resolve()


def _home_workspace_root_default() -> Path:
    return (Path.home() / ".kn_graph" / "libraries" / "workspaces").resolve()


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
    reg_path = (registry_path or _configured_paths.get("registry_path") or registry_path_from_env()).resolve()
    idx_root = (legacy_index_root or _configured_paths.get("index_root") or legacy_index_root_from_env()).resolve()
    configured_ws = _get_configured_workspace_root()
    if configured_ws:
        workspace_base = configured_ws.resolve()
    else:
        workspace_base = workspace_root_base_from_env().resolve()
    workspace_base.mkdir(parents=True, exist_ok=True)
    migrate_legacy_workspace = not str(os.getenv("LITERATURE_LIBRARY_WORKSPACES_ROOT", "") or "").strip()
    legacy_workspace_root = _legacy_workspace_root_default()
    home_workspace_root = _home_workspace_root_default()
    appdata_workspace_root = Path(r"D:\KNGraphAppData\libraries\workspaces").resolve()

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
                    in_legacy = (
                        root_path == legacy_workspace_root
                        or legacy_workspace_root in root_path.parents
                        or root_path == home_workspace_root
                        or home_workspace_root in root_path.parents
                        or root_path == appdata_workspace_root
                        or appdata_workspace_root in root_path.parents
                    )
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


def list_all_workspace_paths(registry: dict[str, Any]) -> list[str]:
    """Return resolved workspace paths for every library in the registry."""
    paths: list[str] = []
    for item in registry.get("libraries", []) if isinstance(registry, dict) else []:
        if not isinstance(item, dict):
            continue
        root = str(item.get("workspace_root", "") or "").strip()
        if not root:
            continue
        try:
            paths.append(str(Path(root).resolve()))
        except Exception:
            paths.append(root)
    return paths


def create_library(
    *,
    library_id: str,
    registry_path: Path | None = None,
    legacy_index_root: Path | None = None,
    workspace_root: str = "",
    set_default: bool = True,
) -> dict[str, Any]:
    target = _safe_library_id(library_id)
    if not target:
        raise ValueError("library_id_required")

    reg_path = (registry_path or _configured_paths.get("registry_path") or registry_path_from_env()).resolve()
    idx_root = (legacy_index_root or _configured_paths.get("index_root") or legacy_index_root_from_env()).resolve()
    idx_root.mkdir(parents=True, exist_ok=True)
    registry = ensure_registry(registry_path=reg_path, legacy_index_root=idx_root)

    if str(workspace_root or "").strip():
        ws_path = Path(workspace_root).resolve()
    else:
        configured_ws = _get_configured_workspace_root()
        ws_base = configured_ws.resolve() if configured_ws is not None else workspace_root_base_from_env().resolve()
        ws_path = ws_base / target
    ws_path.mkdir(parents=True, exist_ok=True)

    # Deploy skills to .claude/skills/ and .agents/skills/ so both Claude Code
    # and Codex auto-discover them when working in this workspace.
    try:
        from kn_graph.services.codex_library_config import bootstrap_workspace_project_skills
        bootstrap_workspace_project_skills(str(ws_path), skill_names=["scholarly-paper-extraction"])
    except Exception:
        pass
    try:
        from kn_graph.services.agent_workspace_guard import ensure_agent_workspace_minimal_config
        ensure_agent_workspace_minimal_config(
            str(ws_path),
            "pipeline_library",
            library_id=target,
        )
    except Exception:
        pass

    index_path = (idx_root / f"{target}.json").resolve()

    index_payload = {
        "library_id": target,
        "paper_count": 0,
        "paper_ids": [],
        "workspace_root": str(ws_path),
        "updated_at": _now_iso(),
    }
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = registry.get("libraries", []) if isinstance(registry, dict) else []
    if not isinstance(rows, list):
        rows = []
    next_rows: list[dict[str, Any]] = []
    found = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = _safe_library_id(str(row.get("library_id", "") or ""))
        if rid == target:
            found = True
            next_rows.append(
                {
                    "library_id": target,
                    "workspace_root": str(ws_path),
                    "index_path": str(index_path),
                    "paper_count": 0,
                    "updated_at": _now_iso(),
                    "state": "active",
                }
            )
        else:
            next_rows.append(row)
    if not found:
        next_rows.append(
            {
                "library_id": target,
                "workspace_root": str(ws_path),
                "index_path": str(index_path),
                "paper_count": 0,
                "updated_at": _now_iso(),
                "state": "active",
            }
        )
    next_rows.sort(key=lambda x: str(x.get("library_id", "")))
    registry["libraries"] = next_rows
    if set_default or not str(registry.get("default_library_id", "") or "").strip():
        registry["default_library_id"] = target
    save_registry(reg_path, registry)

    return {
        "library_id": target,
        "workspace_path": str(ws_path),
        "index_path": str(index_path),
        "default_library_id": str(registry.get("default_library_id", "") or ""),
    }


def delete_library(
    *,
    library_id: str,
    registry_path: Path | None = None,
    legacy_index_root: Path | None = None,
    delete_workspace_data: bool = True,
) -> dict[str, Any]:
    target = _safe_library_id(library_id)
    if not target:
        raise ValueError("library_id_required")

    reg_path = (registry_path or _configured_paths.get("registry_path") or registry_path_from_env()).resolve()
    idx_root = (legacy_index_root or _configured_paths.get("index_root") or legacy_index_root_from_env()).resolve()
    registry = ensure_registry(registry_path=reg_path, legacy_index_root=idx_root)

    rows = registry.get("libraries", []) if isinstance(registry, dict) else []
    if not isinstance(rows, list):
        rows = []
    matched: dict[str, Any] | None = None
    next_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = _safe_library_id(str(row.get("library_id", "") or ""))
        if rid == target and matched is None:
            matched = row
            continue
        next_rows.append(row)
    if matched is None:
        return {"library_id": target, "deleted": False, "reason": "library_not_found"}

    index_path = Path(str(matched.get("index_path", "") or "")).resolve() if str(matched.get("index_path", "") or "").strip() else (idx_root / f"{target}.json").resolve()
    if index_path.exists() and index_path.is_file():
        index_path.unlink(missing_ok=True)

    workspace_path_text = str(matched.get("workspace_root", "") or "").strip()
    deleted_workspace = False
    if delete_workspace_data and workspace_path_text:
        workspace_path = Path(workspace_path_text).resolve()
        # Single-track behavior: if registry points to a real directory, remove it.
        # Keep a minimal safety check to avoid deleting root-like paths.
        is_safe_leaf = len(workspace_path.parts) >= 3 and workspace_path.name.strip() not in {"", ".", ".."}
        if is_safe_leaf and workspace_path.exists() and workspace_path.is_dir():
            shutil.rmtree(workspace_path, ignore_errors=True)
            deleted_workspace = True

    registry["libraries"] = next_rows
    default_id = _safe_library_id(str(registry.get("default_library_id", "") or ""))
    if default_id == target:
        registry["default_library_id"] = str(next_rows[0].get("library_id", "") or "") if next_rows else ""
    save_registry(reg_path, registry)

    return {
        "library_id": target,
        "deleted": True,
        "deleted_workspace": deleted_workspace,
        "workspace_path": workspace_path_text,
        "index_path": str(index_path),
        "default_library_id": str(registry.get("default_library_id", "") or ""),
    }
