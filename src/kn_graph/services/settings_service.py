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
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map, provider_presets  # noqa: F811
        saved = self._read_store().get("categories", {}).get("pipeline", {})
        if not isinstance(saved, dict):
            saved = {}
        mode = str(saved.get("extraction_mode", "") or "fast").strip().lower()
        if mode not in {"fast", "agent"}:
            mode = "fast"
        fast_providers = saved.get("fast_providers", {}) if isinstance(saved.get("fast_providers"), dict) else {}
        active = str(saved.get("fast_provider", "") or "deepseek").strip()
        provider_data = fast_providers.get(active, {}) if isinstance(fast_providers, dict) else {}
        if not isinstance(provider_data, dict):
            provider_data = {}
        defaults_base = (provider_map().get(active, {})).get("base_url", "")
        return {
            "extraction_mode": mode,
            "mineru_api_key": str(saved.get("mineru_api_key", "") or ""),
            "fast_provider": active,
            "fast_model": str(provider_data.get("model", "") or ""),
            "fast_api_key": str(provider_data.get("api_key", "") or ""),
            "fast_base_url": str(provider_data.get("base_url", "") or defaults_base),
            "fast_endpoint_url": str(provider_data.get("endpoint_url", "") or default_endpoint_url(defaults_base)),
            "provider_presets": provider_presets(),
        }

    def _save_pipeline_category(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map  # noqa: F811
        store = self._read_store()
        categories = store.get("categories", {}) if isinstance(store.get("categories"), dict) else {}
        saved = categories.get("pipeline", {}) if isinstance(categories, dict) else {}
        if not isinstance(saved, dict):
            saved = {}
        if "extraction_mode" in body:
            mode = str(body.get("extraction_mode", "") or "fast").strip().lower()
            if mode not in {"fast", "agent"}:
                raise ValueError("settings_validation_failed: pipeline.extraction_mode")
            saved["extraction_mode"] = mode
        if "mineru_api_key" in body:
            saved["mineru_api_key"] = str(body.get("mineru_api_key", "") or "").strip()
        requested = str(body.get("fast_provider", "") or "").strip()
        if requested:
            saved["fast_provider"] = requested
        active = str(saved.get("fast_provider", "") or "deepseek").strip()
        saved.setdefault("fast_providers", {})
        if not isinstance(saved.get("fast_providers"), dict):
            saved["fast_providers"] = {}
        provider_data = saved["fast_providers"].get(active, {}) if isinstance(saved["fast_providers"], dict) else {}
        if not isinstance(provider_data, dict):
            provider_data = {}
        # Map frontend keys (fast_model, fast_api_key, fast_base_url, fast_endpoint_url)
        # to internal per-provider keys (model, api_key, base_url, endpoint_url)
        field_map = [
            ("fast_model", "model"),
            ("fast_api_key", "api_key"),
            ("fast_base_url", "base_url"),
            ("fast_endpoint_url", "endpoint_url"),
        ]
        for body_key, store_key in field_map:
            if body_key in body:
                provider_data[store_key] = str(body.get(body_key, "") or "").strip()
        base_url = str(provider_data.get("base_url", "") or "").strip()
        if not base_url:
            base_url = (provider_map().get(active, {})).get("base_url", "")
            if base_url:
                provider_data["base_url"] = base_url
        if not str(provider_data.get("endpoint_url", "") or "").strip():
            provider_data["endpoint_url"] = default_endpoint_url(base_url)
        saved["fast_providers"][active] = provider_data
        categories["pipeline"] = saved
        store["categories"] = categories
        self._write_store(store)
        return self._get_pipeline_category()

    def _get_pipeline_agent_category(self) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map, provider_presets  # noqa: F811
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
            base_url = (provider_map().get(provider, {})).get("base_url", "")
        return {
            "backend": backend,
            "provider": provider,
            "model": str(saved.get("model", "") or ""),
            "api_key": str(saved.get("api_key", "") or ""),
            "base_url": base_url,
            "endpoint_url": str(saved.get("endpoint_url", "") or default_endpoint_url(base_url)),
            "provider_presets": provider_presets(),
        }

    def _save_pipeline_agent_category(self, body: dict[str, Any]) -> dict[str, Any]:
        from kn_graph.services.cherry_provider_catalog import default_endpoint_url, provider_map  # noqa: F811
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
        for key in ("provider", "model", "api_key", "base_url", "endpoint_url"):
            if key in body:
                saved[key] = str(body.get(key, "") or "").strip()
        provider = str(saved.get("provider", "") or "deepseek").strip()
        base_url = str(saved.get("base_url", "") or "").strip()
        if not base_url:
            base_url = (provider_map().get(provider, {})).get("base_url", "")
            if base_url:
                saved["base_url"] = base_url
        if not str(saved.get("endpoint_url", "") or "").strip():
            saved["endpoint_url"] = default_endpoint_url(base_url)
        categories["pipeline_agent"] = saved
        store["categories"] = categories
        self._write_store(store)
        return self._get_pipeline_agent_category()

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
            "version": 2,
            "categories": [
                {"id": "pipeline", "title": "Pipeline", "restart_required": False},
                {"id": "pipeline_agent", "title": "Pipeline Agent", "restart_required": False},
                {"id": "translation", "title": "翻译", "restart_required": False},
                {"id": "agent_settings", "title": "Agent 设置", "restart_required": True},
            ],
        }

    def get_all(self) -> dict[str, Any]:
        pipeline = attach_provider_meta(self._get_pipeline_category())
        translation = attach_provider_meta(self._get_translation_category())
        return {
            "schema": self.get_schema(),
            "settings": {
                "pipeline": pipeline,
                "pipeline_agent": attach_provider_meta(self._get_pipeline_agent_category()),
                "translation": translation,
                "agent_settings": self._chat_service.get_agent_settings(),
            },
            "updated_at": self._read_store().get("updated_at", ""),
        }

    def update_category(self, category: str, body: dict[str, Any]) -> dict[str, Any]:
        key = str(category or "").strip().lower()
        payload = body if isinstance(body, dict) else {}
        if key == "pipeline":
            return self._save_pipeline_category(payload)
        if key == "pipeline_agent":
            return self._save_pipeline_agent_category(payload)
        if key == "translation":
            return self._save_translation_category(payload)
        if key == "agent_settings":
            return self._chat_service.save_agent_settings(payload)
        raise KeyError(f"unknown_settings_category:{key}")
