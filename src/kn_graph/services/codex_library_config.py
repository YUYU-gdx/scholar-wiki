from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

SKILL_NAME = "回答文献库问题"


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
    return Path(__file__).resolve().parents[3]


def _default_skill_path() -> str:
    return str((_repo_root() / "skills" / "answer_library_question").resolve())


def _skills_template_root() -> Path:
    return (_repo_root() / "skills" / "templates").resolve()


def _default_mcp_server_args() -> list[str]:
    mcp_script = (_repo_root() / "scripts" / "smj_pipeline" / "kn_mcp_server.py").resolve()
    return ["run", "python", str(mcp_script)]


def _iter_skill_template_sources() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    tpl_root = _skills_template_root()
    if tpl_root.exists() and tpl_root.is_dir():
        for child in sorted(tpl_root.iterdir(), key=lambda x: x.name.lower()):
            if not child.is_dir():
                continue
            if not (child / "SKILL.md").exists():
                continue
            out.append((child.name, child.resolve()))
    if out:
        return out
    fallback = Path(_default_skill_path()).resolve()
    if fallback.exists() and (fallback / "SKILL.md").exists():
        out.append((fallback.name, fallback))
    return out


def _copy_single_skill(src: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    src_skill = src / "SKILL.md"
    dst_skill = target / "SKILL.md"
    if src_skill.exists() and src_skill.is_file():
        shutil.copy2(src_skill, dst_skill)
    for rel in ("references", "scripts", "assets"):
        src_dir = src / rel
        dst_dir = target / rel
        if not src_dir.exists() or not src_dir.is_dir():
            continue
        if dst_dir.exists():
            shutil.rmtree(dst_dir, ignore_errors=True)
        shutil.copytree(src_dir, dst_dir)


def bootstrap_workspace_project_skills(workspace_path: str) -> list[dict[str, str]]:
    ws = Path(workspace_path).resolve()
    root = ws / ".codex_project_skills"
    root.mkdir(parents=True, exist_ok=True)
    loaded: list[dict[str, str]] = []
    for folder_name, src in _iter_skill_template_sources():
        target = root / folder_name
        _copy_single_skill(src, target)
        loaded.append({"name": SKILL_NAME, "path": str(target.resolve())})
    return loaded


def _ensure_workspace_skill_copy(workspace_path: str) -> str:
    loaded = bootstrap_workspace_project_skills(workspace_path)
    if loaded:
        return str(loaded[0]["path"])
    return _default_skill_path()


def default_library_codex_config(workspace_path: str = "", library_id: str = "") -> dict[str, Any]:
    ws = Path(workspace_path).resolve() if str(workspace_path or "").strip() else Path()
    codex_home = (ws / ".codex_home").resolve() if str(workspace_path or "").strip() else Path(".codex_home")
    project_skills = bootstrap_workspace_project_skills(str(ws)) if str(workspace_path or "").strip() else [{"name": SKILL_NAME, "path": _default_skill_path()}]
    return {
        "library_id": _safe_library_id(library_id),
        "codex_home": str(codex_home),
        "mcp_servers": [
            {
                "name": "kn_graph_tools",
                "command": "uv",
                "args": _default_mcp_server_args(),
                "env": {},
            }
        ],
        # Workspace-local project skill sources only.
        "project_skills": project_skills,
    }


def config_path_for_workspace(workspace_path: str) -> Path:
    ws = Path(workspace_path).resolve()
    return ws / ".codex" / "library_codex_config.json"


def load_or_init_library_codex_config(workspace_path: str, library_id: str = "") -> dict[str, Any]:
    path = config_path_for_workspace(workspace_path)
    fallback = default_library_codex_config(workspace_path=workspace_path, library_id=library_id)
    loaded_skills = bootstrap_workspace_project_skills(workspace_path)
    if not loaded_skills:
        loaded_skills = list(fallback.get("project_skills", []))
    if path.exists():
        merged = dict(fallback)
        merged.update(_safe_json(path, fallback))

        # Backward compatibility for legacy keys.
        if not isinstance(merged.get("project_skills"), list):
            legacy_name = str(merged.get("skill_name", "") or "").strip()
            legacy_path = str(merged.get("skill_path", "") or "").strip()
            if legacy_path:
                merged["project_skills"] = [{"name": legacy_name or SKILL_NAME, "path": legacy_path}]
            else:
                legacy_paths = merged.get("skills_whitelist", [])
                if isinstance(legacy_paths, list) and legacy_paths:
                    merged["project_skills"] = [
                        {"name": SKILL_NAME, "path": str(x)} for x in legacy_paths if str(x).strip()
                    ]
                else:
                    merged["project_skills"] = list(fallback.get("project_skills", []))

        for key in ("mcp_servers", "project_skills"):
            if not isinstance(merged.get(key), list):
                merged[key] = list(fallback.get(key, []))
        merged["project_skills"] = loaded_skills
        merged["mcp_servers"] = [
            {
                "name": "kn_graph_tools",
                "command": "uv",
                "args": _default_mcp_server_args(),
                "env": {},
            }
        ]

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


def bootstrap_library_codex_config(workspace_path: str, library_id: str = "") -> dict[str, Any]:
    current = load_or_init_library_codex_config(workspace_path=workspace_path, library_id=library_id)
    next_payload = dict(current)
    loaded_skills = bootstrap_workspace_project_skills(workspace_path)
    if loaded_skills:
        next_payload["project_skills"] = loaded_skills
    next_payload["library_id"] = _safe_library_id(str(library_id or next_payload.get("library_id", "") or ""))
    return save_library_codex_config(workspace_path=workspace_path, payload=next_payload)
