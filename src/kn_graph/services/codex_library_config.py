from __future__ import annotations

import json
from pathlib import Path
import shutil
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


from kn_graph._compat import bundle_root
from kn_graph.services.mcp_launch import default_mcp_server_command_and_args

def _repo_root() -> Path:
    return bundle_root()


def _skills_template_root() -> Path:
    return (_repo_root() / "skills" / "templates").resolve()

def _agent_docs_template_root() -> Path:
    return (_skills_template_root() / "agent-docs").resolve()


def _template_skill_path(skill_name: str) -> str:
    return str((_skills_template_root() / skill_name).resolve())


def _default_mcp_server_args() -> list[str]:
    return default_mcp_server_command_and_args()[1]


def _iter_skill_template_sources(skill_names: list[str] | None = None) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    tpl_root = _skills_template_root()
    if tpl_root.exists() and tpl_root.is_dir():
        for child in sorted(tpl_root.iterdir(), key=lambda x: x.name.lower()):
            if not child.is_dir():
                continue
            if not (child / "SKILL.md").exists():
                continue
            if skill_names is not None and child.name not in skill_names:
                continue
            out.append((child.name, child.resolve()))
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


def _sync_workspace_agent_docs(workspace: Path) -> None:
    """Sync CLAUDE.md/AGENTS.md from a single template source."""
    docs_root = _agent_docs_template_root()
    source = docs_root / "template_agent.md"
    if not source.exists():
        for legacy in (
            docs_root / "CLAUDE.md",
            docs_root / "AGENTS.md",
            _repo_root() / "CLAUDE.md",
            _repo_root() / "AGENTS.md",
        ):
            if legacy.exists():
                source = legacy
                break
    if not source.exists():
        return

    for name in ("CLAUDE.md", "AGENTS.md"):
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def bootstrap_workspace_project_skills(workspace_path: str, skill_names: list[str] | None = None) -> list[dict[str, str]]:
    """Deploy skill templates to the correct auto-discovery paths for each backend.

    Claude Code: .claude/skills/<name>/SKILL.md
    Codex:       .agents/skills/<name>/SKILL.md

    If *skill_names* is provided, only skills whose directory name is in the
    list are deployed.
    """
    ws = Path(workspace_path).resolve()
    loaded: list[dict[str, str]] = []

    targets = [
        ws / ".claude" / "skills",   # Claude Code
        ws / ".agents" / "skills",   # Codex
    ]

    for skills_root in targets:
        skills_root.mkdir(parents=True, exist_ok=True)
        for folder_name, src in _iter_skill_template_sources(skill_names):
            target = skills_root / folder_name
            _copy_single_skill(src, target)
            loaded.append({"name": folder_name, "path": str(target.resolve())})
        # Remove skills that are no longer in the allowed set
        if skill_names is not None and skills_root.is_dir():
            for existing in sorted(skills_root.iterdir()):
                if existing.is_dir() and existing.name not in skill_names:
                    shutil.rmtree(str(existing), ignore_errors=True)

    # Clean up legacy path
    legacy_root = ws / ".codex_project_skills"
    if legacy_root.exists():
        shutil.rmtree(str(legacy_root), ignore_errors=True)

    # Keep markdown templates in sync with skill deployment timing.
    _sync_workspace_agent_docs(ws)

    return loaded


def default_library_codex_config(workspace_path: str = "", library_id: str = "") -> dict[str, Any]:
    ws = Path(workspace_path).resolve() if str(workspace_path or "").strip() else Path()
    codex_home = (ws / ".codex_home").resolve() if str(workspace_path or "").strip() else Path(".codex_home")
    if str(workspace_path or "").strip():
        project_skills = bootstrap_workspace_project_skills(str(ws), skill_names=["scholarly-paper-extraction"])
    else:
        project_skills = [{"name": "scholarly-paper-extraction", "path": _template_skill_path("scholarly-paper-extraction")}]
    mcp_command, mcp_args = default_mcp_server_command_and_args()
    return {
        "library_id": _safe_library_id(library_id),
        "codex_home": str(codex_home),
        "mcp_servers": [
            {
                "name": "kn_graph_tools",
                "command": mcp_command,
                "args": mcp_args,
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
    loaded_skills = bootstrap_workspace_project_skills(workspace_path, skill_names=["scholarly-paper-extraction"])
    if not loaded_skills:
        loaded_skills = list(fallback.get("project_skills", []))
    if path.exists():
        merged = dict(fallback)
        merged.update(_safe_json(path, fallback))

        for key in ("mcp_servers", "project_skills"):
            if not isinstance(merged.get(key), list):
                merged[key] = list(fallback.get(key, []))
        merged["project_skills"] = loaded_skills
        mcp_command, mcp_args = default_mcp_server_command_and_args()
        merged["mcp_servers"] = [
            {
                "name": "kn_graph_tools",
                "command": mcp_command,
                "args": mcp_args,
                "env": {},
            }
        ]

        merged["library_id"] = _safe_library_id(str(merged.get("library_id", "") or library_id))
        return merged

    save_library_codex_config(workspace_path, fallback)
    return fallback


def save_library_codex_config(workspace_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = config_path_for_workspace(workspace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    next_payload = dict(payload or {})
    path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_or_init_library_codex_config(
        workspace_path=workspace_path,
        library_id=str(next_payload.get("library_id", "") or ""),
    )


def bootstrap_library_codex_config(workspace_path: str, library_id: str = "") -> dict[str, Any]:
    current = load_or_init_library_codex_config(workspace_path=workspace_path, library_id=library_id)
    next_payload = dict(current)
    loaded_skills = bootstrap_workspace_project_skills(workspace_path, skill_names=["scholarly-paper-extraction"])
    if loaded_skills:
        next_payload["project_skills"] = loaded_skills
    next_payload["library_id"] = _safe_library_id(str(library_id or next_payload.get("library_id", "") or ""))
    return save_library_codex_config(workspace_path=workspace_path, payload=next_payload)
