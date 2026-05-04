from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService
from kn_graph.services.cherry_provider_catalog import attach_provider_meta, default_endpoint_url, provider_map

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_library_registry_module():
    module_path = _SCRIPTS_DIR / "library_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_library_registry_for_settings_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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
        saved = self._read_store().get("categories", {}).get("pipeline", {})
        if not isinstance(saved, dict):
            saved = {}
        defaults = {
            "mineru_api_key": "",
            "extraction_mode": "fast",
            "fast_provider": "deepseek",
            "fast_model": "deepseek-v4-flash",
            "fast_api_key": "",
            "fast_base_url": "https://api.deepseek.com",
            "fast_endpoint_url": "https://api.deepseek.com/v1/chat/completions",
            "agent_provider": "",
            "agent_model": "",
            "agent_note": "预留：后续扩展 Agent 模式参数",
        }
        out = dict(defaults)
        out.update(saved)
        return self._normalize_provider_fields(out, provider_key="fast_provider", base_key="fast_base_url", endpoint_key="fast_endpoint_url")

    def _save_pipeline_category(self, body: dict[str, Any]) -> dict[str, Any]:
        current = self._get_pipeline_category()
        next_payload = dict(current)
        for k in current.keys():
            if k in body:
                next_payload[k] = body.get(k)
        mode = str(next_payload.get("extraction_mode", "fast") or "fast").strip().lower()
        if mode not in {"fast", "agent"}:
            raise ValueError("settings_validation_failed: pipeline.extraction_mode")
        next_payload["extraction_mode"] = mode
        next_payload = self._normalize_provider_fields(next_payload, provider_key="fast_provider", base_key="fast_base_url", endpoint_key="fast_endpoint_url")
        store = self._read_store()
        categories = store.get("categories", {}) if isinstance(store.get("categories"), dict) else {}
        categories["pipeline"] = next_payload
        store["categories"] = categories
        self._write_store(store)
        return next_payload

    def _get_translation_category(self) -> dict[str, Any]:
        cfg = self._chat_service.get_translation_provider_config()
        defaults = {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "endpoint_url": "https://api.deepseek.com/v1/chat/completions",
            "target_lang": "zh",
            "recommendation": "建议优先使用 deepseek-v4-flash。",
        }
        out = dict(defaults)
        if isinstance(cfg, dict):
            out.update(cfg)
        return self._normalize_provider_fields(out, provider_key="provider", base_key="base_url", endpoint_key="endpoint_url")

    def _save_translation_category(self, body: dict[str, Any]) -> dict[str, Any]:
        current = self._get_translation_category()
        next_payload = dict(current)
        for key in ("provider", "model", "api_key", "base_url", "endpoint_url", "target_lang"):
            if key in body:
                next_payload[key] = str(body.get(key, "") or "").strip()
        next_payload = self._normalize_provider_fields(next_payload, provider_key="provider", base_key="base_url", endpoint_key="endpoint_url")
        saved = self._chat_service.save_translation_provider_config(next_payload)
        merged = dict(next_payload)
        if isinstance(saved, dict):
            merged.update(saved)
        merged["recommendation"] = "建议优先使用 deepseek-v4-flash。"
        return merged

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
                "translation": translation,
                "agent_settings": self._chat_service.get_codex_config(),
            },
            "updated_at": self._read_store().get("updated_at", ""),
        }

    def update_category(self, category: str, body: dict[str, Any]) -> dict[str, Any]:
        key = str(category or "").strip().lower()
        payload = body if isinstance(body, dict) else {}
        if key == "pipeline":
            return self._save_pipeline_category(payload)
        if key == "translation":
            return self._save_translation_category(payload)
        if key == "agent_settings":
            return self._chat_service.save_codex_config(payload)
        raise KeyError(f"unknown_settings_category:{key}")
