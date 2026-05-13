from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService
from kn_graph.services.cherry_provider_catalog import attach_provider_meta, default_endpoint_url, provider_map

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_api_key(value: str) -> str:
    """Replace API key bodies with asterisks, showing only the last 4 chars."""
    if not value:
        return value
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def _mask_sensitive_fields(obj: Any) -> Any:
    """Recursively mask any dict value whose key contains 'api_key'."""
    if isinstance(obj, dict):
        result = {}
        for key, val in obj.items():
            if "api_key" in key.lower():
                result[key] = _mask_api_key(str(val) if val else "")
            elif isinstance(val, (dict, list)):
                result[key] = _mask_sensitive_fields(val)
            else:
                result[key] = val
        return result
    if isinstance(obj, list):
        return [_mask_sensitive_fields(item) for item in obj]
    return obj


class SettingsService:
    def __init__(self, settings: Settings, chat_service: ChatService) -> None:
        self._settings = settings
        self._chat_service = chat_service
        self._store_path = self._settings.data_dir / "settings" / "global_settings.json"

    def _read_store(self) -> dict[str, Any]:
        if not self._store_path.exists():
            return {"version": 1, "updated_at": "", "categories": {}}
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "updated_at": "", "categories": {}}
        categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
        if not isinstance(categories, dict):
            categories = {}
        return {"version": int(payload.get("version", 1) or 1), "updated_at": str(payload.get("updated_at", "") or ""), "categories": categories}

    def _write_store(self, payload: dict[str, Any]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        out = dict(payload)
        out["version"] = int(out.get("version", 1) or 1)
        out["updated_at"] = _now_iso()
        self._store_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_pipeline_category(self) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import provider_presets  # noqa: F811
        saved = self._read_store().get("categories", {}).get("pipeline", {})
        if not isinstance(saved, dict):
            saved = {}
        mode = str(saved.get("extraction_mode", "") or "agent").strip().lower()
        if mode not in {"agent"}:
            mode = "agent"
        return {
            "extraction_mode": mode,
            "mineru_api_key": str(saved.get("mineru_api_key", "") or ""),
            "provider_presets": provider_presets(),
        }

    def _save_pipeline_category(self, body: dict[str, Any]) -> dict[str, Any]:
        store = self._read_store()
        categories = store.get("categories", {}) if isinstance(store.get("categories"), dict) else {}
        saved = categories.get("pipeline", {}) if isinstance(categories, dict) else {}
        if not isinstance(saved, dict):
            saved = {}
        if "extraction_mode" in body:
            mode = str(body.get("extraction_mode", "") or "agent").strip().lower()
            if mode not in {"agent"}:
                raise ValueError("settings_validation_failed: pipeline.extraction_mode")
            saved["extraction_mode"] = mode
        if "mineru_api_key" in body:
            saved["mineru_api_key"] = str(body.get("mineru_api_key", "") or "").strip()
        # Force-remove legacy fast extraction fields.
        for legacy_key in ("fast_provider", "fast_providers", "fast_model", "fast_api_key", "fast_base_url", "fast_endpoint_url"):
            saved.pop(legacy_key, None)
        categories["pipeline"] = saved
        store["categories"] = categories
        self._write_store(store)
        return self._get_pipeline_category()

    def _get_pipeline_agent_category(self) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import provider_map, provider_presets  # noqa: F811
        store = self._read_store()
        saved = store.get("categories", {}).get("pipeline_agent", {})
        if not isinstance(saved, dict):
            saved = {}
        backend = str(saved.get("backend", "") or "codex").strip().lower()
        if backend not in ("codex", "claude_code", "gemini_cli"):
            backend = "codex"
        provider = str(saved.get("provider", "") or "deepseek").strip()
        base_url = str(saved.get("base_url", "") or "").strip()
        if not base_url:
            catalog = provider_map().get(provider, {})
            if backend == "claude_code" and catalog.get("anthropic_base_url", "").strip():
                base_url = catalog["anthropic_base_url"].strip()
            else:
                base_url = catalog.get("base_url", "")
        model = str(saved.get("model", "") or "")
        if not model and provider == "deepseek":
            model = "deepseek-v4-flash"
        return {
            "backend": backend,
            "provider": provider,
            "model": model,
            "api_key": str(saved.get("api_key", "") or ""),
            "base_url": base_url,
            "reasoning_effort": str(saved.get("reasoning_effort", "") or ""),
            "provider_presets": provider_presets(),
            "reasoning_effort_options": {
                "codex": ["none", "minimal", "low", "medium", "high", "xhigh"],
                "claude_code": ["low", "medium", "high", "max"],
                "gemini_cli": [],
            },
        }

    def _save_pipeline_agent_category(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import provider_map  # noqa: F811
        store = self._read_store()
        categories = store.get("categories", {}) if isinstance(store.get("categories"), dict) else {}
        saved = categories.get("pipeline_agent", {}) if isinstance(categories.get("pipeline_agent"), dict) else {}
        if not isinstance(saved, dict):
            saved = {}
        if "backend" in body:
            backend = str(body.get("backend", "") or "codex").strip().lower()
            if backend not in ("codex", "claude_code", "gemini_cli"):
                raise ValueError("settings_validation_failed: pipeline_agent.backend")
            saved["backend"] = backend
        backend = str(saved.get("backend", "") or "codex").strip().lower()
        for key in ("provider", "model", "api_key", "base_url"):
            if key in body:
                saved[key] = str(body.get(key, "") or "").strip()
        if "reasoning_effort" in body:
            effort = str(body.get("reasoning_effort", "") or "").strip().lower()
            allowed_by_backend = {
                "codex": {"", "none", "minimal", "low", "medium", "high", "xhigh"},
                "claude_code": {"", "low", "medium", "high", "max"},
                "gemini_cli": {""},
            }
            allowed = allowed_by_backend.get(backend, {""})
            if effort not in allowed:
                raise ValueError("settings_validation_failed: pipeline_agent.reasoning_effort")
            saved["reasoning_effort"] = effort
        provider = str(saved.get("provider", "") or "deepseek").strip()
        base_url = str(saved.get("base_url", "") or "").strip()
        if not base_url:
            catalog = provider_map().get(provider, {})
            if backend == "claude_code" and catalog.get("anthropic_base_url", "").strip():
                saved["base_url"] = catalog["anthropic_base_url"].strip()
            elif catalog.get("base_url", ""):
                saved["base_url"] = catalog["base_url"]
        # Keep only one URL field for agent settings.
        saved.pop("endpoint_url", None)
        categories["pipeline_agent"] = saved
        store["categories"] = categories
        self._write_store(store)

        # Mirror pipeline agent settings to every library workspace so that
        # running `claude` or `codex` directly in a library workspace picks
        # up the same provider / model / api_key / base_url.
        self._deploy_pipeline_agent_to_library_workspaces(saved)
        try:
            from kn_graph.services.agent_workspace_guard import ensure_all_agent_workspaces_minimal_config
            ensure_all_agent_workspaces_minimal_config(self._settings)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "pipeline_agent_settings: failed to sync minimal agent workspace configs",
                exc_info=True,
            )

        return self._get_pipeline_agent_category()

    def _deploy_pipeline_agent_to_library_workspaces(self, saved: dict[str, Any]) -> None:
        backend = str(saved.get("backend", "") or "").strip()
        provider = str(saved.get("provider", "") or "").strip()
        model = str(saved.get("model", "") or "").strip()
        api_key = str(saved.get("api_key", "") or "").strip()
        base_url = str(saved.get("base_url", "") or "").strip()
        if not any((provider, model, api_key, base_url)):
            return
        try:
            from kn_graph.services.workspace_agent_config import deploy_to_all_library_workspaces
            deploy_to_all_library_workspaces(
                registry_path=str(self._settings.registry_path),
                backend=backend,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to deploy pipeline_agent config to library workspaces",
                exc_info=True,
            )

    def _get_embedding_category(self) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_embedding_endpoint_url, provider_presets  # noqa: F811
        store = self._read_store()
        saved = store.get("categories", {}).get("embedding", {})
        if not isinstance(saved, dict):
            saved = {}
        provider = str(saved.get("provider", "") or "zhipu").strip()
        providers = saved.get("providers", {}) if isinstance(saved.get("providers"), dict) else {}
        provider_data = providers.get(provider, {}) if isinstance(providers, dict) else {}
        if not isinstance(provider_data, dict):
            provider_data = {}
        endpoint_url = str(provider_data.get("endpoint_url", "") or "").strip()
        if not endpoint_url and provider == "zhipu":
            endpoint_url = "https://open.bigmodel.cn/api/paas/v4/embeddings"
        elif not endpoint_url:
            endpoint_url = default_embedding_endpoint_url("")
        model = str(provider_data.get("model", "") or "")
        if not model and provider == "zhipu":
            model = "embedding-3"
        return {
            "provider": provider,
            "model": model,
            "api_key": str(provider_data.get("api_key", "") or ""),
            "endpoint_url": endpoint_url,
            "provider_presets": provider_presets(),
        }

    def _save_embedding_category(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_embedding_endpoint_url  # noqa: F811
        store = self._read_store()
        categories = store.get("categories", {}) if isinstance(store.get("categories"), dict) else {}
        saved = categories.get("embedding", {}) if isinstance(categories, dict) else {}
        if not isinstance(saved, dict):
            saved = {}
        requested = str(body.get("provider", "") or "").strip()
        if requested:
            saved["provider"] = requested
        active = str(saved.get("provider", "") or "zhipu").strip()
        saved.setdefault("providers", {})
        if not isinstance(saved.get("providers"), dict):
            saved["providers"] = {}
        provider_data = saved["providers"].get(active, {}) if isinstance(saved["providers"], dict) else {}
        if not isinstance(provider_data, dict):
            provider_data = {}
        for key in ("model", "api_key", "endpoint_url"):
            if key in body:
                provider_data[key] = str(body.get(key, "") or "").strip()
        if not str(provider_data.get("endpoint_url", "") or "").strip():
            provider_data["endpoint_url"] = default_embedding_endpoint_url("")
        saved["providers"][active] = provider_data
        categories["embedding"] = saved
        store["categories"] = categories
        self._write_store(store)
        return self._get_embedding_category()

    def _get_translation_category(self) -> dict[str, Any]:
        return self._chat_service.get_translation_provider_config()

    def _save_translation_category(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._chat_service.save_translation_provider_config(body)

    def _normalize_provider_fields(self, payload: dict[str, Any], *, provider_key: str, base_key: str, endpoint_key: str) -> dict[str, Any]:
        out = dict(payload)
        provider_id = str(out.get(provider_key, "") or "").strip().lower()
        presets = provider_map()
        if provider_id in presets:
            if not str(out.get(base_key, "") or "").strip():
                out[base_key] = presets[provider_id]["base_url"]
        base_url = str(out.get(base_key, "") or "").strip()
        if not str(out.get(endpoint_key, "") or "").strip():
            out[endpoint_key] = default_endpoint_url(base_url)
        return out

    def get_schema(self) -> dict[str, Any]:
        return {
            "version": 3,
            "categories": [
                {"id": "pipeline", "title": "Pipeline", "restart_required": False},
                {"id": "pipeline_agent", "title": "Pipeline Agent", "restart_required": False},
                {"id": "embedding", "title": "Embedding 嵌入模型", "restart_required": False},
                {"id": "translation", "title": "翻译", "restart_required": False},
                {"id": "agent_settings", "title": "Agent 设置", "restart_required": True},
            ],
        }

    def get_all(self) -> dict[str, Any]:
        pipeline = attach_provider_meta(self._get_pipeline_category())
        translation = attach_provider_meta(self._get_translation_category())
        raw = {
            "schema": self.get_schema(),
            "settings": {
                "pipeline": pipeline,
                "pipeline_agent": attach_provider_meta(self._get_pipeline_agent_category()),
                "embedding": attach_provider_meta(self._get_embedding_category()),
                "translation": translation,
                "agent_settings": self._chat_service.get_agent_settings(),
            },
            "updated_at": self._read_store().get("updated_at", ""),
        }
        # Mask API keys in the response so raw secrets are never exposed over HTTP.
        return _mask_sensitive_fields(raw)

    def update_category(self, category: str, body: dict[str, Any]) -> dict[str, Any]:
        key = str(category or "").strip().lower()
        payload = body if isinstance(body, dict) else {}
        if key == "pipeline":
            return _mask_sensitive_fields(self._save_pipeline_category(payload))
        if key == "pipeline_agent":
            return _mask_sensitive_fields(self._save_pipeline_agent_category(payload))
        if key == "embedding":
            return _mask_sensitive_fields(self._save_embedding_category(payload))
        if key == "translation":
            return _mask_sensitive_fields(self._save_translation_category(payload))
        if key == "agent_settings":
            return _mask_sensitive_fields(self._chat_service.save_agent_settings(payload))
        raise KeyError(f"unknown_settings_category:{key}")

    def get_agent_template(self, target: str) -> dict[str, Any]:
        path = self._resolve_agent_template_path(target)
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        return {
            "target": str(target or "").strip().lower(),
            "path": str(path.resolve()),
            "exists": path.exists(),
            "content": content,
        }

    def save_agent_template(self, target: str, content: str) -> dict[str, Any]:
        path = self._resolve_agent_template_path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content or ""), encoding="utf-8")
        return self.get_agent_template(target)

    def _resolve_agent_template_path(self, target: str) -> Path:
        key = str(target or "").strip().lower()
        root = Path.cwd()
        mapping: dict[str, Path] = {
            "pipeline_skill": Path("skills/templates/scholarly-paper-extraction/SKILL.md"),
            "qa_skill": Path("skills/templates/answer_library_question/SKILL.md"),
            "claude_md": Path("skills/templates/agent-docs/CLAUDE.md"),
            "agent_md": Path("skills/templates/agent-docs/CLAUDE.md"),
        }
        rel = mapping.get(key)
        if rel is None:
            raise KeyError(f"unknown_agent_template_target:{key}")
        path = root / rel
        if key == "claude_md" and not path.exists():
            legacy = root / "CLAUDE.md"
            if legacy.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        return path
