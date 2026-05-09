from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from kn_graph.config import Settings

_PLUGIN_IDS = ("superpowers@openai-curated", "github@openai-curated")


def _default_mcp_server(workspace_path: str, library_id: str = "") -> dict[str, Any]:
    mcp_script = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline" / "kn_mcp_server.py"
    env: dict[str, str] = {}
    if str(library_id or "").strip():
        env["KN_DEFAULT_LIBRARY_ID"] = str(library_id or "").strip()
    return {
        "name": "kn_graph_tools",
        "command": "uv",
        "args": ["run", "python", str(mcp_script)],
        "env": env,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_mcp_json(workspace: Path, *, library_id: str = "") -> bool:
    path = workspace / ".mcp.json"
    server = _default_mcp_server(str(workspace), library_id=library_id)
    payload = {
        "mcpServers": {
            "kn_graph_tools": {
                "command": server["command"],
                "args": server["args"],
                "env": server["env"],
            }
        }
    }
    current = _read_json(path)
    if current == payload:
        return False
    _write_json(path, payload)
    return True


def _set_plugin_enabled_false_in_toml(text: str, plugin_id: str) -> tuple[str, bool]:
    section_header = f'[plugins."{plugin_id}"]'
    lines = text.splitlines()
    changed = False

    idx = -1
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            idx = i
            break

    if idx == -1:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(section_header)
        lines.append("enabled = false")
        changed = True
        return ("\n".join(lines) + "\n", changed)

    end = len(lines)
    for j in range(idx + 1, len(lines)):
        if re.match(r"^\s*\[", lines[j]):
            end = j
            break

    enabled_idx = -1
    for j in range(idx + 1, end):
        if re.match(r"^\s*enabled\s*=", lines[j]):
            enabled_idx = j
            break

    if enabled_idx == -1:
        lines.insert(idx + 1, "enabled = false")
        changed = True
    else:
        normalized = "enabled = false"
        if lines[enabled_idx].strip() != normalized:
            lines[enabled_idx] = normalized
            changed = True

    return ("\n".join(lines) + "\n", changed)


def _ensure_codex_plugins_disabled(workspace: Path) -> bool:
    path = workspace / ".codex" / "config.toml"
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
    else:
        text = ""
    changed_any = False
    for plugin_id in _PLUGIN_IDS:
        text, changed = _set_plugin_enabled_false_in_toml(text, plugin_id)
        changed_any = changed_any or changed
    if changed_any or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    return False


def _ensure_claude_plugins_disabled(workspace: Path) -> bool:
    path = workspace / ".claude" / "settings.local.json"
    payload = _read_json(path)
    enabled_plugins = payload.get("enabledPlugins", {})
    if not isinstance(enabled_plugins, dict):
        enabled_plugins = {}
    changed = False
    for plugin_id in _PLUGIN_IDS:
        if enabled_plugins.get(plugin_id) is not False:
            enabled_plugins[plugin_id] = False
            changed = True
    if changed or "enabledPlugins" not in payload:
        payload["enabledPlugins"] = enabled_plugins
        _write_json(path, payload)
        return True
    return False


def ensure_agent_workspace_minimal_config(
    workspace_path: str,
    instance_type: str,
    *,
    library_id: str = "",
) -> dict[str, Any]:
    """Ensure a workspace exposes only the required skills/MCP/plugins.

    instance_type:
    - "chat_root": keep only answer_library_question
    - "pipeline_library": keep only scholarly-paper-extraction
    """
    ws = Path(str(workspace_path or "").strip()).resolve()
    if not ws.exists() or not ws.is_dir():
        raise RuntimeError(f"workspace_path_invalid:{ws}")

    if instance_type == "chat_root":
        skill_names = ["answer_library_question"]
    elif instance_type == "pipeline_library":
        skill_names = ["scholarly-paper-extraction"]
    else:
        raise ValueError(f"instance_type_invalid:{instance_type}")

    changed = {
        "skills": False,
        "mcp": False,
        "plugins_codex": False,
        "plugins_claude": False,
        "library_codex_config": False,
    }

    from kn_graph.services.codex_library_config import (
        bootstrap_workspace_project_skills,
        load_or_init_library_codex_config,
        save_library_codex_config,
    )

    loaded_skills = bootstrap_workspace_project_skills(str(ws), skill_names=skill_names)
    changed["skills"] = True if loaded_skills else False

    changed["mcp"] = _ensure_mcp_json(ws, library_id=library_id)
    changed["plugins_codex"] = _ensure_codex_plugins_disabled(ws)
    changed["plugins_claude"] = _ensure_claude_plugins_disabled(ws)

    if instance_type == "pipeline_library":
        cfg = load_or_init_library_codex_config(workspace_path=str(ws), library_id=library_id)
        next_cfg = dict(cfg)
        next_cfg["mcp_servers"] = [_default_mcp_server(str(ws), library_id=library_id)]
        next_cfg["project_skills"] = loaded_skills
        if next_cfg != cfg:
            save_library_codex_config(workspace_path=str(ws), payload=next_cfg)
            changed["library_codex_config"] = True

    return {
        "workspace_path": str(ws),
        "instance_type": instance_type,
        "changed": changed,
        "loaded_skills": loaded_skills,
    }


def ensure_all_agent_workspaces_minimal_config(settings: Settings) -> dict[str, Any]:
    """Run startup-wide minimal config checks for chat root + all libraries."""
    from kn_graph.services.library_registry import ensure_registry

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    root_ws = str(settings.workspaces_dir.resolve())
    try:
        results.append(ensure_agent_workspace_minimal_config(root_ws, "chat_root"))
    except Exception as exc:
        errors.append(f"chat_root:{exc}")

    try:
        reg = ensure_registry(registry_path=settings.registry_path)
        rows = reg.get("libraries", []) if isinstance(reg, dict) else []
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ws_path = str(row.get("workspace_root", "") or "").strip()
            if not ws_path:
                continue
            library_id = str(row.get("library_id", "") or "").strip()
            try:
                results.append(
                    ensure_agent_workspace_minimal_config(
                        ws_path,
                        "pipeline_library",
                        library_id=library_id,
                    )
                )
            except Exception as exc:
                errors.append(f"library:{ws_path}:{exc}")
    except Exception as exc:
        errors.append(f"registry:{exc}")

    return {"results": results, "errors": errors}
