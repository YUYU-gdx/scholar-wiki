from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterator

from kn_graph.config import Settings

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"


def _load_chat_service_class():
    module_path = _SCRIPTS_DIR / "chat_service.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_chat_service_for_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.ChatService, mod.InMemoryChatStore


def _load_provider_registry_class():
    module_path = _SCRIPTS_DIR / "llm" / "provider_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_provider_registry_for_chat_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.ProviderRegistry


def _load_agent_runner_module():
    module_path = _SCRIPTS_DIR / "agent_runner.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_agent_runner_for_chat_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_library_codex_config_module():
    module_path = _SCRIPTS_DIR / "codex_library_config.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_codex_library_config_for_chat_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_library_registry_module():
    module_path = _SCRIPTS_DIR / "library_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_library_registry_for_chat_svc", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ChatService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._chat: Any = None

    def _ensure_chat(self) -> Any:
        if self._chat is not None:
            return self._chat
        ChatServiceCls, _ = _load_chat_service_class()

        from kn_graph.services.literature_service import LiteratureService
        literature_svc = LiteratureService(self._settings)
        literature = literature_svc._ensure_service()

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
        return self._chat

    def _resolve_library_workspace(self, library_id: str) -> str:
        target = str(library_id or "").strip()
        if not target:
            return ""
        try:
            reg_mod = _load_library_registry_module()
            registry = reg_mod.ensure_registry(
                registry_path=self._settings.registry_path,
            )
            return str(reg_mod.resolve_workspace_root(registry, target) or "").strip()
        except Exception:
            return ""

    def _resolve_library_codex_config(self, workspace_path: str, library_id: str) -> dict[str, Any]:
        try:
            codex_cfg_mod = _load_library_codex_config_module()
            return codex_cfg_mod.load_or_init_library_codex_config(workspace_path=workspace_path, library_id=library_id)
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
        provider: str = "codex",
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
            agent_runner_mod = _load_agent_runner_module()
            config_path = self._settings.codex_config_path
            cfg = agent_runner_mod.load_codex_config(config_path)
            return {
                "app_server_command": str(cfg.app_server_command or ""),
                "app_server_args": list(cfg.app_server_args),
                "healthcheck_args": list(cfg.healthcheck_args),
                "timeout_seconds": int(cfg.timeout_seconds),
                "install_command": str(cfg.install_command or ""),
                "extra_env": dict(cfg.extra_env),
                "model": str(cfg.model or ""),
                "approval_policy": str(cfg.approval_policy or ""),
                "sandbox_mode": str(cfg.sandbox_mode or ""),
                "personality": str(cfg.personality or ""),
                "mcp_servers": list(cfg.mcp_servers),
                "config_path": str(config_path.resolve()),
            }
        except Exception:
            return {}

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
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map  # noqa: F811
        agent_defaults: dict[str, dict[str, str]] = {
            "codex":       {"provider": "deepseek", "model": ""},
            "claude_code": {"provider": "anthropic", "model": ""},
            "gemini_cli":  {"provider": "gemini", "model": ""},
            "hermes":      {"provider": "deepseek", "model": ""},
            "opencode":    {"provider": "deepseek", "model": ""},
            "openclaw":    {"provider": "deepseek", "model": ""},
        }
        defaults = agent_defaults.get(agent_id, {"provider": "deepseek", "model": ""})
        provider_id = defaults["provider"]
        base_url = (provider_map().get(provider_id, {})).get("base_url", "")
        return {
            "provider": provider_id,
            "model": defaults["model"],
            "api_key": "",
            "base_url": base_url,
            "endpoint_url": default_endpoint_url(base_url),
        }

    def get_agent_settings(self) -> dict[str, Any]:
        """Read agent settings from the active agent's config file."""
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map, provider_presets  # noqa: F811
        known = {"codex", "claude_code", "gemini_cli", "hermes", "opencode", "openclaw"}
        current_agent = self._get_current_agent()
        if current_agent not in known:
            current_agent = "codex"
        config = self._read_agent_config(current_agent)
        defaults = self._default_agent_provider_config(current_agent)
        provider_id = str(config.get("provider", "") or defaults["provider"]).strip()
        base_url = str(config.get("base_url", "") or "").strip()
        if not base_url:
            base_url = (provider_map().get(provider_id, {})).get("base_url", "")
        return {
            "current_agent": current_agent,
            "available_agents": sorted(known),
            "provider": provider_id,
            "model": str(config.get("model", "") or defaults["model"]),
            "api_key": str(config.get("api_key", "") or ""),
            "base_url": base_url,
            "endpoint_url": str(config.get("endpoint_url", "") or default_endpoint_url(base_url)),
            "provider_presets": provider_presets(),
        }

    def save_agent_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map  # noqa: F811
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
        if "endpoint_url" in body:
            updates["endpoint_url"] = str(body.get("endpoint_url", "") or "").strip()
        # Auto-fill base_url from provider if switching
        new_provider = str(updates.get("provider", "") or "").strip()
        if new_provider and "base_url" not in updates:
            catalog_base = (provider_map().get(new_provider, {})).get("base_url", "")
            if catalog_base:
                updates["base_url"] = catalog_base
        if updates:
            base = str(updates.get("base_url", "") or "").strip()
            if not str(updates.get("endpoint_url", "") or "").strip():
                updates["endpoint_url"] = default_endpoint_url(base)
            self._write_agent_config(current_agent, updates)
        return self.get_agent_settings()

    def save_codex_config(self, body: dict[str, Any]) -> dict[str, Any]:
        agent_runner_mod = _load_agent_runner_module()
        config_path = self._settings.codex_config_path
        existing = self.get_codex_config()
        next_payload = dict(existing)
        for key in (
            "app_server_command",
            "app_server_args",
            "healthcheck_args",
            "timeout_seconds",
            "install_command",
            "extra_env",
            "model",
            "approval_policy",
            "sandbox_mode",
            "personality",
            "mcp_servers",
        ):
            if key in body:
                next_payload[key] = body.get(key)
        to_write = {k: v for k, v in next_payload.items() if k != "config_path"}
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(to_write, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_codex_config()

    def check_codex_health(self) -> dict[str, Any]:
        try:
            agent_runner_mod = _load_agent_runner_module()
            config_path = self._settings.codex_config_path
            cfg = agent_runner_mod.load_codex_config(config_path)
            runner = agent_runner_mod.CodexRunner(cfg)
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
            ProviderRegistry = _load_provider_registry_class()
            registry = ProviderRegistry(config_path=Path(self._settings.llm_provider_config_path))
            registry.reload()
            payload = registry.get_config()
            payload["config_path"] = str(registry.config_path)
            return payload
        except Exception:
            return {}

    def update_provider_config(self, body: dict[str, Any]) -> dict[str, Any]:
        ProviderRegistry = _load_provider_registry_class()
        registry = ProviderRegistry(config_path=Path(self._settings.llm_provider_config_path))
        saved = registry.update_config(body)
        saved["config_path"] = str(registry.config_path)
        return saved

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
        return {
            "active_provider": active,
            "provider": active,
            "model": str(provider_data.get("model", "") or ""),
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
    ) -> dict[str, Any]:
        src = str(text or "").strip()
        if not src:
            raise ValueError("text_required")
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

        ProviderRegistry = _load_provider_registry_class()
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
        return {
            "translated_text": translated,
            "provider": resolved_provider,
            "model": resolved_model,
            "target_lang": resolved_target,
            "latency_ms": latency_ms,
        }

    def test_provider(self, provider: str, model: str = "", options: dict[str, Any] | None = None, prompt: str = "") -> dict[str, Any]:
        if options is None:
            options = {}
        ProviderRegistry = _load_provider_registry_class()
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
            codex_cfg_mod = _load_library_codex_config_module()
            cfg = codex_cfg_mod.load_or_init_library_codex_config(workspace_path=workspace, library_id=lib)
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
            codex_cfg_mod = _load_library_codex_config_module()
            current = codex_cfg_mod.load_or_init_library_codex_config(workspace_path=workspace, library_id=lib)
            next_payload = dict(current)
            for key in ("codex_home", "mcp_servers", "project_skills"):
                if key in body:
                    next_payload[key] = body.get(key)
            next_payload["library_id"] = lib
            saved = codex_cfg_mod.save_library_codex_config(workspace_path=workspace, payload=next_payload)
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
            codex_cfg_mod = _load_library_codex_config_module()
            cfg = codex_cfg_mod.bootstrap_library_codex_config(workspace_path=workspace, library_id=lib)
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
