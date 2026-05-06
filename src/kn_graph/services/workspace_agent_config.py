"""Write agent provider settings to Claude Code and Codex native config files.

When the user saves Pipeline Agent or Agent settings in the UI, this module
mirrors the provider config to the workspace directories so that running
``claude`` or ``codex`` directly in those workspaces picks up the same settings.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def deploy_to_workspace(
    workspace_path: str,
    backend: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> None:
    """Write agent config into *workspace_path* for the specified *backend*.

    *backend* must be one of ``"claude_code"`` or ``"codex"``.  Other backends
    are silently skipped (no workspace-level config format defined yet).
    """
    ws = Path(workspace_path).resolve()
    _deploy = _BACKEND_DISPATCH.get(backend)
    if _deploy is not None:
        _deploy(ws, provider, model, api_key, base_url)


def deploy_to_all_library_workspaces(
    registry_path: str,
    backend: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> None:
    """Call ``deploy_to_workspace`` for every library workspace in the registry."""
    from kn_graph.services.library_registry import (
        ensure_registry,
        list_all_workspace_paths,
    )

    reg = ensure_registry(registry_path=Path(registry_path).resolve())
    for ws_path in list_all_workspace_paths(reg):
        try:
            deploy_to_workspace(ws_path, backend, provider, model, api_key, base_url)
        except Exception:
            logger.warning("Failed to deploy agent config to library workspace: %s", ws_path, exc_info=True)


def deploy_to_root_workspace(
    workspaces_dir: str,
    backend: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> None:
    """Call ``deploy_to_workspace`` on the root workspace directory."""
    deploy_to_workspace(workspaces_dir, backend, provider, model, api_key, base_url)


# ---------------------------------------------------------------------------
# Claude Code — .claude/settings.local.json
# ---------------------------------------------------------------------------


def _resolve_anthropic_base_url(provider: str, base_url: str) -> str:
    """Return the Anthropic-compatible base URL for *provider*.

    Looks up ``anthropic_base_url`` from the provider catalog.  Falls back
    to the generic *base_url* when the provider doesn't declare one.
    """
    try:
        from kn_graph.services.cherry_provider_catalog import provider_map
        catalog = provider_map().get(provider, {})
        anthro = str(catalog.get("anthropic_base_url", "") or "").strip()
        if anthro:
            return anthro
    except Exception:
        pass
    return str(base_url or "").strip()


def _build_claude_code_payload(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    env: dict[str, str] = {}
    anthro_url = _resolve_anthropic_base_url(provider, base_url)
    if anthro_url:
        env["ANTHROPIC_BASE_URL"] = anthro_url
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    if model:
        env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = model
        env["ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"] = model

    payload: dict[str, Any] = {}
    if env:
        payload["env"] = env

    return payload


def _write_claude_code_settings(
    ws: Path,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> None:
    payload = _build_claude_code_payload(provider, model, api_key, base_url)
    if not payload:
        return

    claude_dir = ws / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.local.json"

    # Merge with existing so we don't clobber unrelated settings.
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}

    # Deep-merge the env block
    merged = dict(existing)
    existing_env = merged.get("env", {})
    if not isinstance(existing_env, dict):
        existing_env = {}
    merged_env = dict(existing_env)
    merged_env.update(payload.get("env", {}))
    if merged_env:
        merged["env"] = merged_env
    elif "env" in merged:
        del merged["env"]

    settings_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Codex — .codex/config.toml
# ---------------------------------------------------------------------------

_CODEX_PROVIDER_ID = "kn_graph"


def _build_codex_toml(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> str:
    lines: list[str] = []

    if model:
        lines.append(f'model = "{model}"')
    lines.append(f'model_provider = "{_CODEX_PROVIDER_ID}"')
    lines.append("")

    lines.append(f"[model_providers.{_CODEX_PROVIDER_ID}]")
    lines.append(f'name = "KN Graph ({provider})"')
    if base_url:
        lines.append(f'base_url = "{base_url}"')
    if api_key:
        lines.append(f'experimental_bearer_token = "{api_key}"')

    return "\n".join(lines) + "\n"


def _write_codex_config(
    ws: Path,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> None:
    tom = _build_codex_toml(provider, model, api_key, base_url)

    codex_dir = ws / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text(tom, encoding="utf-8")


# ---------------------------------------------------------------------------
# Backend dispatch — maps agent backend id → workspace config writer
# ---------------------------------------------------------------------------

_BACKEND_DISPATCH: dict[str, Any] = {
    "claude_code": _write_claude_code_settings,
    "codex": _write_codex_config,
}
