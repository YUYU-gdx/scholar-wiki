from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(fallback)
    return payload if isinstance(payload, dict) else dict(fallback)


def _safe_library_id(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    out = []
    for ch in text:
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_skill_path() -> str:
    return str((_repo_root() / "skills" / "answer_library_question").resolve())


def default_library_codex_config(workspace_path: str = "", library_id: str = "") -> dict[str, Any]:
    ws = Path(workspace_path).resolve() if str(workspace_path or "").strip() else Path()
    codex_home = (ws / ".codex_home").resolve() if str(workspace_path or "").strip() else Path(".codex_home")
    skill_path = _default_skill_path()
    return {
        "library_id": _safe_library_id(library_id),
        "codex_home": str(codex_home),
        "mcp_servers": [
            {
                "name": "kn_graph_tools",
                "command": "uv",
                "args": ["run", "python", "-m", "scripts.smj_pipeline.kn_mcp_server"],
                "env": {},
            }
        ],
        # Workspace-local project skill sources only.
        "project_skills": [
            {
                "name": "回答文献库问题",
                "path": skill_path,
            }
        ],
    }


def config_path_for_workspace(workspace_path: str) -> Path:
    ws = Path(workspace_path).resolve()
    return ws / ".codex" / "library_codex_config.json"


def load_or_init_library_codex_config(workspace_path: str, library_id: str = "") -> dict[str, Any]:
    path = config_path_for_workspace(workspace_path)
    fallback = default_library_codex_config(workspace_path=workspace_path, library_id=library_id)
    if path.exists():
        merged = dict(fallback)
        merged.update(_safe_json(path, fallback))

        # Backward compatibility for legacy keys.
        if not isinstance(merged.get("project_skills"), list):
            legacy_name = str(merged.get("skill_name", "") or "").strip()
            legacy_path = str(merged.get("skill_path", "") or "").strip()
            if legacy_path:
                merged["project_skills"] = [{"name": legacy_name or "回答文献库问题", "path": legacy_path}]
            else:
                legacy_paths = merged.get("skills_whitelist", [])
                if isinstance(legacy_paths, list) and legacy_paths:
                    merged["project_skills"] = [
                        {"name": "回答文献库问题", "path": str(x)} for x in legacy_paths if str(x).strip()
                    ]
                else:
                    merged["project_skills"] = list(fallback.get("project_skills", []))

        for key in ("mcp_servers", "project_skills"):
            if not isinstance(merged.get(key), list):
                merged[key] = list(fallback.get(key, []))

        merged["library_id"] = _safe_library_id(str(merged.get("library_id", "") or library_id))

        for key in ("mcp_whitelist", "skills_whitelist", "skill_name", "skill_path"):
            merged.pop(key, None)
        return merged

    save_library_codex_config(workspace_path, fallback)
    return fallback


def save_library_codex_config(workspace_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = config_path_for_workspace(workspace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    next_payload = dict(payload or {})
    for key in ("mcp_whitelist", "skills_whitelist", "skill_name", "skill_path"):
        next_payload.pop(key, None)
    path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_or_init_library_codex_config(
        workspace_path=workspace_path,
        library_id=str(next_payload.get("library_id", "") or ""),
    )
