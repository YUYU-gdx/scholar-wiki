from __future__ import annotations

import json
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from kn_graph.config import Settings
from kn_graph._compat import bundle_root

from kn_graph.services.chat_legacy import ChatService as LegacyChatService
from kn_graph.services.agent_runner import AgentRunnerFactory
from kn_graph.services.codex_library_config import load_or_init_library_codex_config, bootstrap_library_codex_config, save_library_codex_config as _save_cfg
from kn_graph.providers.registry import ProviderRegistry  # noqa: E402
from kn_graph.services.agent_runner import CodexRunner  # noqa: E402


class ChatService:
    TRANSLATION_LABEL_HTML = '<span style="color:#16a34a;"><strong>译文</strong></span>'

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._chat: Any = None
        self._translation_jobs_lock = threading.Lock()
        self._translation_jobs: dict[str, dict[str, Any]] = {}

    def _ensure_chat(self) -> Any:
        if self._chat is not None:
            # Keep agent_backend in sync with the persisted setting so the
            # frontend agent selector takes effect without a restart.
            current = self._get_current_agent()
            if current:
                self._chat._agent_backend = current
            return self._chat
        ChatServiceCls = LegacyChatService

        from kn_graph.services.literature_service import LiteratureService
        literature = LiteratureService(self._settings)

        self._chat = ChatServiceCls(
            literature_search_fn=lambda q, k, library_id="": (
                literature.search(
                    query=q,
                    top_k=k,
                    levels=["sentence", "paragraph"],
                    library_id=library_id,
                    keyword_weight=0.4,
                    rag_weight=0.6,
                    include_expanded_context=True,
                )
                if literature is not None
                else {"keyword_hits": [], "rag_hits": [], "merged_hits": []}
            ),
            graph_search_fn=None,
            paper_get_fn=None,
            variable_get_fn=None,
            library_workspace_resolver_fn=self._resolve_library_workspace,
            library_codex_config_resolver_fn=self._resolve_library_codex_config,
        )
        # Inject settings so legacy chat can access non-agent config
        self._chat._settings = self._settings
        # Deploy the chat / Q&A skill to the root workspace so Claude Code
        # (whose cwd is the root workspace) auto-discovers it.
        from kn_graph.services.codex_library_config import bootstrap_workspace_project_skills
        root_ws = str(self._settings.workspaces_dir.resolve())
        bootstrap_workspace_project_skills(root_ws, skill_names=["answer_library_question"])
        # Set the initial backend from persisted settings.
        current = self._get_current_agent()
        if current:
            self._chat._agent_backend = current
        return self._chat

    def _resolve_library_workspace(self, library_id: str) -> str:
        target = str(library_id or "").strip()
        if not target:
            return ""
        ws = (self._settings.workspaces_dir / target).resolve()
        if not ws.exists() or not ws.is_dir():
            return ""
        return str(ws)

    def _resolve_library_codex_config(self, workspace_path: str, library_id: str) -> dict[str, Any]:
        try:
            return load_or_init_library_codex_config(workspace_path=workspace_path, library_id=library_id)
        except Exception:
            return {}

    def list_sessions(self, library_id: str) -> dict[str, Any]:
        chat = self._ensure_chat()
        return {"sessions": chat.list_sessions(library_id=library_id)}

    def get_session(self, session_id: str, library_id: str) -> dict[str, Any] | None:
        chat = self._ensure_chat()
        return chat.get_session_with_messages(session_id=session_id, library_id=library_id)

    def create_session(self, title: str = "", library_id: str = "") -> dict[str, Any]:
        chat = self._ensure_chat()
        return chat.create_session(title=title, default_mode="agent", library_id=library_id)

    def delete_session(self, session_id: str, library_id: str = "") -> dict[str, Any]:
        chat = self._ensure_chat()
        return chat.delete_session(session_id=session_id, undo_window_seconds=5, library_id=library_id)

    def restore_session(self, session_id: str, library_id: str = "") -> dict[str, Any]:
        chat = self._ensure_chat()
        return chat.restore_session(session_id=session_id, library_id=library_id)

    def send_message(
        self,
        session_id: str,
        content: str,
        mode: str = "agent",
        provider: str = "",
        model: str = "codex-local",
        stream: bool = True,
        library_id: str = "",
    ) -> dict[str, Any]:
        chat = self._ensure_chat()
        return chat.submit_message(
            session_id=session_id,
            content=content,
            mode=mode,
            provider=provider,
            model=model,
            stream=stream,
            library_id=library_id,
        )

    def read_events(self, message_id: str, cursor: int = 0, wait_seconds: float = 5.0) -> tuple[list[dict[str, Any]], int, bool]:
        chat = self._ensure_chat()
        return chat.read_events(message_id=message_id, cursor=cursor, wait_seconds=wait_seconds)

    def get_codex_config(self) -> dict[str, Any]:
        try:
            config_path = self._settings.codex_config_path
            if config_path.exists():
                data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    result = dict(data)
                    result.setdefault("config_path", str(config_path.resolve()))
                    return result
        except Exception:
            pass
        return {
            "model": "gpt-5.2",
            "mcp_servers": [
                {
                    "name": "kn_graph_tools",
                    "command": "uv",
                    "args": [
                        "run",
                        "python",
                        str(
                            bundle_root()
                            / "scripts"
                            / "smj_pipeline"
                            / "kn_mcp_server.py"
                        ),
                    ],
                    "env": {},
                }
            ],
            "config_path": str(self._settings.codex_config_path.resolve()),
        }

    def _agent_settings_path(self) -> Path:
        return self._settings.data_dir / "chat" / "agent_settings.json"

    def _agent_config_path(self, agent_id: str) -> Path:
        """Return the config file path for a given agent."""
        if agent_id == "codex":
            return self._settings.codex_config_path
        return self._settings.data_dir / "chat" / f"{agent_id}_config.json"

    def _read_agent_config(self, agent_id: str) -> dict[str, Any]:
        """Read the agent's actual config file."""
        path = self._agent_config_path(agent_id)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _write_agent_config(self, agent_id: str, updates: dict[str, Any]) -> None:
        """Merge updates into the agent's config file."""
        path = self._agent_config_path(agent_id)
        existing = self._read_agent_config(agent_id)
        existing.update(updates)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_current_agent(self) -> str:
        """Read current_agent from agent_settings.json."""
        path = self._agent_settings_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    agent = str(data.get("current_agent", "") or "").strip()
                    if agent:
                        return agent
            except Exception:
                pass
        return "codex"

    def _set_current_agent(self, agent_id: str) -> None:
        path = self._agent_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"current_agent": agent_id}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _default_agent_provider_config(self, agent_id: str) -> dict[str, str]:
        from kn_graph.services.cherry_provider_catalog import provider_map  # noqa: F811
        agent_defaults: dict[str, dict[str, str]] = {
            "codex":       {"provider": "deepseek", "model": "deepseek-v4-flash"},
            "claude_code": {"provider": "anthropic", "model": ""},
            "gemini_cli":  {"provider": "gemini", "model": ""},
            "hermes":      {"provider": "deepseek", "model": "deepseek-v4-flash"},
            "opencode":    {"provider": "deepseek", "model": "deepseek-v4-flash"},
            "openclaw":    {"provider": "deepseek", "model": "deepseek-v4-flash"},
        }
        defaults = agent_defaults.get(agent_id, {"provider": "deepseek", "model": ""})
        provider_id = defaults["provider"]
        base_url = (provider_map().get(provider_id, {})).get("base_url", "")
        return {
            "provider": provider_id,
            "model": defaults["model"],
            "api_key": "",
            "base_url": base_url,
        }

    def get_agent_settings(self) -> dict[str, Any]:
        """Read agent settings from the active agent's config file."""
        from kn_graph.services.cherry_provider_catalog import provider_map, provider_presets  # noqa: F811
        known = {"codex", "claude_code", "gemini_cli", "hermes", "opencode", "openclaw"}
        current_agent = self._get_current_agent()
        if current_agent not in known:
            current_agent = "codex"
        config = self._read_agent_config(current_agent)
        defaults = self._default_agent_provider_config(current_agent)
        provider_id = str(config.get("provider", "") or defaults["provider"]).strip()
        base_url = str(config.get("base_url", "") or "").strip()
        if not base_url:
            catalog = provider_map().get(provider_id, {})
            if current_agent == "claude_code" and catalog.get("anthropic_base_url", "").strip():
                base_url = catalog["anthropic_base_url"].strip()
            else:
                base_url = catalog.get("base_url", "")
        return {
            "current_agent": current_agent,
            "available_agents": sorted(known),
            "provider": provider_id,
            "model": str(config.get("model", "") or defaults["model"]),
            "api_key": str(config.get("api_key", "") or ""),
            "base_url": base_url,
            "provider_presets": provider_presets(),
        }

    def save_agent_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import provider_map  # noqa: F811
        known = {"codex", "claude_code", "gemini_cli", "hermes", "opencode", "openclaw"}
        # Handle agent switch
        requested_agent = str(body.get("current_agent", "") or "").strip()
        if requested_agent and requested_agent in known:
            self._set_current_agent(requested_agent)
        current_agent = self._get_current_agent()
        if current_agent not in known:
            current_agent = "codex"
            self._set_current_agent(current_agent)
        # Build updates for agent config file
        updates: dict[str, Any] = {}
        if "provider" in body:
            updates["provider"] = str(body.get("provider", "") or "").strip()
        if "model" in body:
            updates["model"] = str(body.get("model", "") or "").strip()
        if "api_key" in body:
            updates["api_key"] = str(body.get("api_key", "") or "").strip()
        if "base_url" in body:
            updates["base_url"] = str(body.get("base_url", "") or "").strip()
        # Auto-fill base_url from provider if switching
        new_provider = str(updates.get("provider", "") or "").strip()
        if new_provider and "base_url" not in updates:
            catalog = provider_map().get(new_provider, {})
            if current_agent == "claude_code" and catalog.get("anthropic_base_url", "").strip():
                updates["base_url"] = catalog["anthropic_base_url"].strip()
            elif catalog.get("base_url", ""):
                updates["base_url"] = catalog["base_url"]
        if updates:
            self._write_agent_config(current_agent, updates)

        # Mirror agent settings to the root workspace so that running
        # `claude` or `codex` directly there picks up the same provider.
        self._deploy_agent_settings_to_root_workspace(current_agent, updates)
        try:
            from kn_graph.services.agent_workspace_guard import ensure_all_agent_workspaces_minimal_config
            ensure_all_agent_workspaces_minimal_config(self._settings)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "save_agent_settings: failed to sync minimal agent workspace configs",
                exc_info=True,
            )

        return self.get_agent_settings()

    def _deploy_agent_settings_to_root_workspace(self, backend: str, updates: dict[str, Any]) -> None:
        provider = str(updates.get("provider", "") or "").strip()
        model = str(updates.get("model", "") or "").strip()
        api_key = str(updates.get("api_key", "") or "").strip()
        base_url = str(updates.get("base_url", "") or "").strip()
        if not any((provider, model, api_key, base_url)):
            return
        try:
            from kn_graph.services.workspace_agent_config import deploy_to_root_workspace
            deploy_to_root_workspace(
                workspaces_dir=str(self._settings.workspaces_dir.resolve()),
                backend=backend,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to deploy agent_settings to root workspace",
                exc_info=True,
            )

    def save_codex_config(self, body: dict[str, Any]) -> dict[str, Any]:
        config_path = self._settings.codex_config_path
        existing = self.get_codex_config()
        next_payload = dict(existing)
        for key in ("model", "mcp_servers", "install_command"):
            if key in body:
                next_payload[key] = body.get(key)
        to_write = {k: v for k, v in next_payload.items() if k != "config_path"}
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(to_write, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_codex_config()

    def check_codex_health(self) -> dict[str, Any]:
        try:
            runner = CodexRunner(codex_bin="codex")
            health = runner.health()
            return {
                "backend": "codex",
                "available": bool(health.get("available")),
                "reason": str(health.get("reason", "") or ""),
                "version": str(health.get("version", "") or ""),
            }
        except Exception as exc:
            return {
                "backend": "codex",
                "available": False,
                "reason": str(exc),
            }

    def get_provider_config(self) -> dict[str, Any]:
        try:
            registry = ProviderRegistry(config_path=Path(self._settings.llm_provider_config_path))
            registry.reload()
            payload = registry.get_config()
            payload["config_path"] = str(registry.config_path)
            return payload
        except Exception:
            return {}

    def update_provider_config(self, body: dict[str, Any]) -> dict[str, Any]:
        registry = ProviderRegistry(config_path=Path(self._settings.llm_provider_config_path))
        saved = registry.update_config(body)
        saved["config_path"] = str(registry.config_path)
        return saved

    # ------------------------------------------------------------------
    # Agent install info & test
    # ------------------------------------------------------------------

    _INSTALL_INFO: dict[str, dict[str, Any]] = {
        "claude_code": {
            "command": "npm install -g @anthropic-ai/claude-code",
            "binary": "claude",
            "verify": "claude --version",
            "display_name": "Claude Code",
        },
        "codex": {
            "command": "npm install -g @openai/codex",
            "binary": "codex",
            "verify": "codex --version",
            "display_name": "Codex",
        },
        "gemini_cli": {
            "command": "npm install -g @google/gemini-cli",
            "binary": "gemini",
            "verify": "gemini --version",
            "display_name": "Gemini CLI",
        },
        "opencode": {
            "command": "npm install -g opencode-ai@latest",
            "binary": "opencode",
            "verify": "opencode --version",
            "display_name": "OpenCode",
        },
        "openclaw": {
            "command": "npm install -g openclaw@latest",
            "binary": "openclaw",
            "verify": "openclaw --version",
            "display_name": "OpenClaw",
        },
        "hermes": {
            "command": "",
            "binary": "",
            "verify": "",
            "display_name": "Hermes",
            "not_available": True,
        },
    }

    def get_agent_install_info(self, agent_id: str) -> dict[str, Any]:
        known = {"codex", "claude_code", "gemini_cli", "hermes", "opencode", "openclaw"}
        agent_id = str(agent_id or "").strip().lower()
        if agent_id not in known:
            raise ValueError(f"unknown_agent:{agent_id}")
        info = dict(self._INSTALL_INFO.get(agent_id, {}))
        info["agent_id"] = agent_id
        return info

    def test_agent(self, agent_id: str) -> dict[str, Any]:
        import shutil
        import subprocess as _sp
        from datetime import datetime, timezone

        known = {"codex", "claude_code", "gemini_cli", "hermes", "opencode", "openclaw"}
        agent_id = str(agent_id or "").strip().lower()
        if agent_id not in known:
            raise ValueError(f"unknown_agent:{agent_id}")

        info = self._INSTALL_INFO.get(agent_id, {})
        binary = str(info.get("binary", "") or "").strip()
        checks: list[dict[str, Any]] = []

        # Stage 1: CLI check
        if binary:
            resolved = shutil.which(binary)
            if resolved:
                try:
                    proc = _sp.run(
                        [resolved, "--version"],
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                    version_text = ((proc.stdout or proc.stderr or "").strip().splitlines())[:1]
                    checks.append({
                        "name": "cli_installed",
                        "passed": proc.returncode == 0,
                        "binary": resolved,
                        "version": version_text[0] if version_text else "",
                        "stage": "cli_check",
                    })
                except Exception as exc:
                    checks.append({
                        "name": "cli_installed",
                        "passed": False,
                        "binary": resolved,
                        "error": str(exc),
                        "stage": "cli_check",
                    })
            else:
                checks.append({
                    "name": "cli_installed",
                    "passed": False,
                    "binary": binary,
                    "error": "binary_not_found",
                    "suggestion": f"请点击安装按钮安装 {info.get('display_name', agent_id)} CLI",
                    "stage": "cli_check",
                })
        else:
            checks.append({
                "name": "cli_installed",
                "passed": False,
                "error": "agent_not_installable",
                "suggestion": f"Agent '{agent_id}' 暂不支持安装",
                "stage": "cli_check",
            })

        # Stage 2: Workspace config
        root_ws = self._settings.workspaces_dir.resolve()
        claude_md = root_ws / "CLAUDE.md"
        checks.append({
            "name": "workspace_claude_md",
            "passed": claude_md.exists(),
            "path": str(claude_md),
            "stage": "workspace_config",
            "suggestion": "" if claude_md.exists() else "工作区缺少 CLAUDE.md，Agent 可能缺少项目上下文",
        })

        mcp_json = root_ws / ".mcp.json"
        mcp_ok = False
        if mcp_json.exists():
            try:
                mcp_data = json.loads(mcp_json.read_text(encoding="utf-8"))
                mcp_ok = isinstance(mcp_data, dict) and "mcpServers" in mcp_data
            except Exception:
                pass
        checks.append({
            "name": "workspace_mcp_json",
            "passed": mcp_ok,
            "path": str(mcp_json),
            "stage": "workspace_config",
            "suggestion": "" if mcp_ok else "工作区缺少有效的 .mcp.json，Agent 无法使用 MCP 工具",
        })

        # Stage 3: Agent config file
        agent_cfg_path = self._agent_config_path(agent_id)
        cfg_exists = agent_cfg_path.exists()
        checks.append({
            "name": "agent_config_file",
            "passed": cfg_exists,
            "path": str(agent_cfg_path),
            "stage": "agent_config",
            "suggestion": "" if cfg_exists else "请先在 Agent 设置中保存 provider/model/api_key 配置",
        })

        # Stage 4: claude_code SDK
        if agent_id == "claude_code":
            try:
                import claude_agent_sdk  # noqa: F401
                checks.append({"name": "claude_agent_sdk", "passed": True, "stage": "sdk_check"})
            except ImportError:
                checks.append({
                    "name": "claude_agent_sdk",
                    "passed": False,
                    "stage": "sdk_check",
                    "suggestion": "claude-agent-sdk 未安装，请运行: pip install claude-agent-sdk",
                })

        passed = [c for c in checks if c["passed"]]
        failed = [c for c in checks if not c["passed"]]
        return {
            "agent_id": agent_id,
            "ok": len(failed) == 0,
            "passed_count": len(passed),
            "failed_count": len(failed),
            "checks": checks,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def _translation_config_path(self) -> Path:
        return self._settings.data_dir / "chat" / "translation_provider_config.json"

    def get_translation_provider_config(self) -> dict[str, Any]:
        """Return the active translation provider's config + presets list."""
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map, provider_presets  # noqa: F811
        path = self._translation_config_path()
        data: dict[str, Any] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                data = {}
        active = str(data.get("active_provider", "") or "").strip()
        if not active:
            active = "deepseek"
        providers = data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}
        provider_data = providers.get(active, {}) if isinstance(providers, dict) else {}
        if not isinstance(provider_data, dict):
            provider_data = {}
        defaults_base = (provider_map().get(active, {})).get("base_url", "")
        model = str(provider_data.get("model", "") or "")
        if not model and active == "deepseek":
            model = "deepseek-v4-flash"
        return {
            "active_provider": active,
            "provider": active,
            "model": model,
            "api_key": str(provider_data.get("api_key", "") or ""),
            "base_url": str(provider_data.get("base_url", "") or defaults_base),
            "endpoint_url": str(provider_data.get("endpoint_url", "") or default_endpoint_url(defaults_base)),
            "target_lang": str(data.get("target_lang", "") or "zh"),
            "provider_presets": provider_presets(),
        }

    def save_translation_provider_config(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map  # noqa: F811
        path = self._translation_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                data = {}
        requested_provider = str(body.get("provider", "") or "").strip()
        if requested_provider:
            data["active_provider"] = requested_provider
        active = str(data.get("active_provider", "") or "deepseek").strip()
        if not active:
            active = "deepseek"
            data["active_provider"] = active
        data.setdefault("providers", {})
        if not isinstance(data.get("providers"), dict):
            data["providers"] = {}
        provider_data = data["providers"].get(active, {}) if isinstance(data["providers"], dict) else {}
        if not isinstance(provider_data, dict):
            provider_data = {}
        for key in ("model", "api_key", "base_url", "endpoint_url"):
            if key in body:
                provider_data[key] = str(body.get(key, "") or "").strip()
        base_url = str(provider_data.get("base_url", "") or "").strip()
        if not base_url:
            base_url = (provider_map().get(active, {})).get("base_url", "")
            if base_url:
                provider_data["base_url"] = base_url
        if not str(provider_data.get("endpoint_url", "") or "").strip():
            provider_data["endpoint_url"] = default_endpoint_url(base_url)
        data["providers"][active] = provider_data
        if "target_lang" in body:
            data["target_lang"] = str(body.get("target_lang", "") or "zh").strip()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_translation_provider_config()

    def translate_text(
        self,
        text: str,
        target_lang: str = "zh",
        provider: str = "deepseek",
        model: str = "deepseek-v4-flash",
        api_key: str = "",
        base_url: str = "",
        endpoint_url: str = "",
        compare_by_paragraph: bool = False,
    ) -> dict[str, Any]:
        src = str(text or "").strip()
        if not src:
            raise ValueError("text_required")
        if bool(compare_by_paragraph):
            return self.translate_markdown_bilingual(
                markdown_text=src,
                target_lang=target_lang,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                endpoint_url=endpoint_url,
            )
        cfg = self.get_translation_provider_config()
        resolved_provider = str(provider or cfg.get("provider") or "deepseek").strip()
        resolved_model = str(model or cfg.get("model") or "deepseek-v4-flash").strip()
        resolved_target = str(target_lang or cfg.get("target_lang") or "zh").strip() or "zh"
        resolved_api_key = str(api_key or cfg.get("api_key") or "").strip()
        resolved_base_url = str(base_url or cfg.get("base_url") or "").strip()
        resolved_endpoint = str(endpoint_url or cfg.get("endpoint_url") or "").strip()

        if not resolved_endpoint and resolved_base_url:
            resolved_endpoint = resolved_base_url.rstrip("/") + "/v1/chat/completions"
        if not resolved_endpoint:
            resolved_endpoint = "https://api.deepseek.com/v1/chat/completions"
        if not resolved_base_url:
            resolved_base_url = resolved_endpoint.rsplit("/", 3)[0] if "/v1/" in resolved_endpoint else resolved_endpoint

        registry = ProviderRegistry(config_path=Path(self._settings.llm_provider_config_path))
        options = {
            "api_key": resolved_api_key,
            "base_url": resolved_endpoint,
            "timeout_seconds": 90,
            "temperature": 0.1,
        }
        messages = [
            {"role": "system", "content": f"You are a translator. Translate the user text into {resolved_target}. Output translation only."},
            {"role": "user", "content": src},
        ]
        begin = time.perf_counter()
        client = registry.create_message_client(provider=resolved_provider, model=resolved_model, options=options)
        translated = str(client.complete_messages(messages=messages, timeout_seconds=90) or "").strip()
        latency_ms = int((time.perf_counter() - begin) * 1000)
        decorated = self._decorate_translation_line(translated)
        return {
            "translated_text": translated,
            "formatted_text": decorated,
            "provider": resolved_provider,
            "model": resolved_model,
            "target_lang": resolved_target,
            "latency_ms": latency_ms,
        }

    def _translate_single_text(
        self,
        text: str,
        target_lang: str,
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        endpoint_url: str,
    ) -> dict[str, Any]:
        return self.translate_text(
            text=text,
            target_lang=target_lang,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            endpoint_url=endpoint_url,
            compare_by_paragraph=False,
        )

    def _decorate_translation_line(self, translated: str) -> str:
        return f"{self.TRANSLATION_LABEL_HTML}: {str(translated or '').strip()}".rstrip()

    def translate_markdown_bilingual(
        self,
        markdown_text: str,
        target_lang: str = "zh",
        provider: str = "deepseek",
        model: str = "deepseek-v4-flash",
        api_key: str = "",
        base_url: str = "",
        endpoint_url: str = "",
        progress_cb: Any | None = None,
    ) -> dict[str, Any]:
        src = str(markdown_text or "").strip()
        if not src:
            raise ValueError("text_required")
        blocks = self._split_markdown_blocks(str(markdown_text or ""))
        out: list[str] = []
        total_latency = 0
        translated_blocks = 0
        last_meta: dict[str, Any] = {}
        total_work = max(1, len([x for x in blocks if x.strip() and not self._is_fenced_code_block(x)]))
        done_work = 0
        for block in blocks:
            out.append(block)
            if not block.strip():
                continue
            if self._is_fenced_code_block(block):
                continue
            result = self._translate_single_text(
                text=block,
                target_lang=target_lang,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                endpoint_url=endpoint_url,
            )
            translated = str(result.get("translated_text", "") or "").strip()
            out.append(self._decorate_translation_line(translated))
            translated_blocks += 1
            total_latency += int(result.get("latency_ms", 0) or 0)
            last_meta = result
            done_work += 1
            if callable(progress_cb):
                progress_cb(done_work, total_work)
        return {
            "translated_text": "\n\n".join(out).strip(),
            "formatted_text": "\n\n".join(out).strip(),
            "compare_by_paragraph": True,
            "translated_blocks": translated_blocks,
            "provider": str(last_meta.get("provider", provider) or provider),
            "model": str(last_meta.get("model", model) or model),
            "target_lang": str(last_meta.get("target_lang", target_lang) or target_lang),
            "latency_ms": total_latency,
        }

    def submit_markdown_translation_job(
        self,
        markdown_text: str,
        target_lang: str = "zh",
        provider: str = "deepseek",
        model: str = "deepseek-v4-flash",
        api_key: str = "",
        base_url: str = "",
        endpoint_url: str = "",
    ) -> dict[str, Any]:
        src = str(markdown_text or "").strip()
        if not src:
            raise ValueError("text_required")
        job_id = f"tr_{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._translation_jobs_lock:
            self._translation_jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "progress": 0,
                "created_at": now,
                "updated_at": now,
                "result": None,
                "error": "",
            }

        def _run() -> None:
            self._update_translation_job(job_id, status="running", progress=0)
            try:
                result = self.translate_markdown_bilingual(
                    markdown_text=markdown_text,
                    target_lang=target_lang,
                    provider=provider,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    endpoint_url=endpoint_url,
                    progress_cb=lambda done, total: self._update_translation_job(
                        job_id,
                        status="running",
                        progress=int(max(0, min(100, round((done / max(1, total)) * 100)))),
                    ),
                )
                self._update_translation_job(job_id, status="completed", progress=100, result=result)
            except Exception as exc:
                self._update_translation_job(job_id, status="failed", error=str(exc))

        threading.Thread(target=_run, name=f"translation-job-{job_id}", daemon=True).start()
        return {"job_id": job_id, "status": "queued", "progress": 0}

    def get_translation_job(self, job_id: str) -> dict[str, Any]:
        jid = str(job_id or "").strip()
        if not jid:
            raise ValueError("job_id_required")
        with self._translation_jobs_lock:
            row = self._translation_jobs.get(jid)
            if not isinstance(row, dict):
                raise ValueError("translation_job_not_found")
            return dict(row)

    def _update_translation_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._translation_jobs_lock:
            row = self._translation_jobs.get(job_id)
            if not isinstance(row, dict):
                return
            if status is not None:
                row["status"] = status
            if progress is not None:
                row["progress"] = int(max(0, min(100, progress)))
            if result is not None:
                row["result"] = result
            if error is not None:
                row["error"] = str(error or "")
            row["updated_at"] = now

    def _split_markdown_blocks(self, text: str) -> list[str]:
        if not text:
            return []
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        chunks: list[str] = []
        current: list[str] = []
        for line in normalized.split("\n"):
            if not line.strip():
                if current:
                    chunks.append("\n".join(current).strip("\n"))
                    current = []
                continue
            current.append(line)
        if current:
            chunks.append("\n".join(current).strip("\n"))
        return chunks

    def _is_fenced_code_block(self, block: str) -> bool:
        lines = [x for x in block.splitlines() if x.strip()]
        if len(lines) < 2:
            return False
        start = lines[0].strip()
        end = lines[-1].strip()
        return (start.startswith("```") and end.startswith("```")) or (start.startswith("~~~") and end.startswith("~~~"))

    def test_provider(self, provider: str, model: str = "", options: dict[str, Any] | None = None, prompt: str = "") -> dict[str, Any]:
        if options is None:
            options = {}
        registry = ProviderRegistry(config_path=Path(self._settings.llm_provider_config_path))
        if not provider:
            return {"error": "provider_required"}
        resolved = registry.resolve_provider_id(provider)
        if not model:
            cfg = registry.get_config()
            providers = cfg.get("providers", []) if isinstance(cfg, dict) else []
            if isinstance(providers, list):
                for item in providers:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("id", "") or "").strip().lower() == resolved:
                        model = str(item.get("default_model", "") or "").strip()
                        break
        timeout_seconds = int(options.get("timeout_seconds", 20) or 20)
        client = registry.create_message_client(provider=provider, model=model or None, options=options)
        text = str(
            client.complete_messages(
                messages=[
                    {"role": "system", "content": "You are a connection checker. Keep responses minimal."},
                    {"role": "user", "content": prompt or "Reply with OK only."},
                ],
                timeout_seconds=timeout_seconds,
            )
        ).strip()
        return {"ok": True, "provider": resolved, "model": model, "response_preview": text[:120]}

    def get_library_codex_config(self, library_id: str) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            return {"error": "library_id_required"}
        workspace = self._resolve_library_workspace(lib)
        if not workspace:
            return {"error": "codex_workspace_path_missing", "library_id": lib}
        try:
            cfg = load_or_init_library_codex_config(workspace_path=workspace, library_id=lib)
            cfg["workspace_path"] = workspace
            return cfg
        except Exception:
            return {"error": "library_codex_config_unavailable", "library_id": lib}

    def save_library_codex_config(self, library_id: str, body: dict[str, Any]) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            return {"error": "library_id_required"}
        workspace = self._resolve_library_workspace(lib)
        if not workspace:
            return {"error": "codex_workspace_path_missing", "library_id": lib}
        try:
            current = load_or_init_library_codex_config(workspace_path=workspace, library_id=lib)
            next_payload = dict(current)
            for key in ("codex_home", "mcp_servers", "project_skills"):
                if key in body:
                    next_payload[key] = body.get(key)
            next_payload["library_id"] = lib
            saved = _save_cfg(workspace_path=workspace, payload=next_payload)
            saved["workspace_path"] = workspace
            return saved
        except Exception:
            return {"error": "library_codex_config_unavailable", "library_id": lib}

    def bootstrap_library_codex_skills(self, library_id: str) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            return {"error": "library_id_required"}
        workspace = self._resolve_library_workspace(lib)
        if not workspace:
            return {"error": "codex_workspace_path_missing", "library_id": lib}
        try:
            cfg = bootstrap_library_codex_config(workspace_path=workspace, library_id=lib)
            skills = cfg.get("project_skills", [])
            return {
                "ok": True,
                "library_id": lib,
                "workspace_path": workspace,
                "loaded_skills": skills if isinstance(skills, list) else [],
                "config": cfg,
            }
        except Exception:
            return {"error": "library_codex_config_unavailable", "library_id": lib}
