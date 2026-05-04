from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService

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
        if not isinstance(payload, dict):
            return {"version": 1, "updated_at": "", "categories": {}}
        categories = payload.get("categories", {})
        if not isinstance(categories, dict):
            categories = {}
        return {
            "version": int(payload.get("version", 1) or 1),
            "updated_at": str(payload.get("updated_at", "") or ""),
            "categories": categories,
        }

    def _write_store(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        out = dict(payload)
        out["version"] = int(out.get("version", 1) or 1)
        out["updated_at"] = _now_iso()
        self._store_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def _get_pipeline_category(self) -> dict[str, Any]:
        store = self._read_store()
        categories = store.get("categories", {})
        saved = categories.get("pipeline", {}) if isinstance(categories, dict) else {}
        if not isinstance(saved, dict):
            saved = {}
        defaults = {
            "executor": str(self._settings.pipeline_executor or "inline"),
            "job_store_dsn": str(self._settings.pipeline_job_store_dsn or ""),
            "redis_url": str(self._settings.pipeline_redis_url or "redis://127.0.0.1:6379/0"),
            "mineru_api_key_env": "MINERU_API_KEY",
            "mineru_base_url": "https://mineru.net/api/v4",
            "mineru_model_version": "vlm",
            "llm_provider": "",
            "llm_model": "",
            "llm_api_key_env": "",
            "llm_base_url": "",
            "max_poll_seconds": 3600,
            "poll_interval_seconds": 8.0,
            "max_retries": 3,
            "retry_delays": "8,20,60",
        }
        out = dict(defaults)
        out.update(saved)
        return out

    def _save_pipeline_category(self, body: dict[str, Any]) -> dict[str, Any]:
        current = self._get_pipeline_category()
        next_payload = dict(current)
        allowed = set(current.keys())
        for k, v in body.items():
            if k not in allowed:
                continue
            next_payload[k] = v
        next_payload = self._validate_pipeline_category(next_payload)
        store = self._read_store()
        categories = store.get("categories", {})
        if not isinstance(categories, dict):
            categories = {}
        categories["pipeline"] = next_payload
        store["categories"] = categories
        self._write_store(store)
        return next_payload

    def _validate_pipeline_category(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        executor = str(out.get("executor", "inline") or "inline").strip().lower()
        if executor not in {"inline", "celery"}:
            raise ValueError("settings_validation_failed: pipeline.executor")
        out["executor"] = executor
        out["job_store_dsn"] = str(out.get("job_store_dsn", "") or "").strip()
        out["redis_url"] = str(out.get("redis_url", "") or "").strip()
        out["mineru_api_key_env"] = str(out.get("mineru_api_key_env", "MINERU_API_KEY") or "MINERU_API_KEY").strip()
        out["mineru_base_url"] = str(out.get("mineru_base_url", "https://mineru.net/api/v4") or "https://mineru.net/api/v4").strip()
        out["mineru_model_version"] = str(out.get("mineru_model_version", "vlm") or "vlm").strip()
        out["llm_provider"] = str(out.get("llm_provider", "") or "").strip()
        out["llm_model"] = str(out.get("llm_model", "") or "").strip()
        out["llm_api_key_env"] = str(out.get("llm_api_key_env", "") or "").strip()
        out["llm_base_url"] = str(out.get("llm_base_url", "") or "").strip()
        try:
            out["max_poll_seconds"] = max(30, min(86400, int(out.get("max_poll_seconds", 3600) or 3600)))
            out["poll_interval_seconds"] = max(0.5, min(120.0, float(out.get("poll_interval_seconds", 8.0) or 8.0)))
            out["max_retries"] = max(0, min(20, int(out.get("max_retries", 3) or 3)))
        except Exception as exc:
            raise ValueError("settings_validation_failed: pipeline.numeric_fields") from exc
        retry_delays = str(out.get("retry_delays", "8,20,60") or "8,20,60").strip()
        if not retry_delays:
            retry_delays = "8,20,60"
        out["retry_delays"] = retry_delays
        return out

    def _get_library_defaults(self) -> dict[str, Any]:
        reg_mod = _load_library_registry_module()
        registry = reg_mod.ensure_registry(registry_path=self._settings.registry_path, legacy_index_root=self._settings.indexes_dir)
        return {
            "default_library_id": str(registry.get("default_library_id", "") or ""),
            "registry_path": str(self._settings.registry_path),
            "workspaces_dir": str(self._settings.workspaces_dir),
            "indexes_dir": str(self._settings.indexes_dir),
        }

    def _save_library_defaults(self, body: dict[str, Any]) -> dict[str, Any]:
        default_library_id = str(body.get("default_library_id", "") or "").strip()
        reg_mod = _load_library_registry_module()
        registry = reg_mod.ensure_registry(registry_path=self._settings.registry_path, legacy_index_root=self._settings.indexes_dir)
        registry["default_library_id"] = default_library_id
        reg_mod.save_registry(self._settings.registry_path, registry)
        return self._get_library_defaults()

    def get_schema(self) -> dict[str, Any]:
        return {
            "categories": [
                {
                    "id": "pipeline",
                    "title": "Pipeline",
                    "restart_required": False,
                    "fields": [
                        {"key": "executor", "type": "select", "options": ["inline", "celery"]},
                        {"key": "job_store_dsn", "type": "text"},
                        {"key": "redis_url", "type": "text"},
                        {"key": "mineru_api_key_env", "type": "text"},
                        {"key": "mineru_base_url", "type": "text"},
                        {"key": "mineru_model_version", "type": "text"},
                        {"key": "llm_provider", "type": "text"},
                        {"key": "llm_model", "type": "text"},
                        {"key": "llm_api_key_env", "type": "text"},
                        {"key": "llm_base_url", "type": "text"},
                        {"key": "max_poll_seconds", "type": "number"},
                        {"key": "poll_interval_seconds", "type": "number"},
                        {"key": "max_retries", "type": "number"},
                        {"key": "retry_delays", "type": "text"},
                    ],
                },
                {"id": "llm_providers", "title": "LLM Providers", "restart_required": False},
                {
                    "id": "translation",
                    "title": "Translation",
                    "restart_required": False,
                    "fields": [
                        {"key": "provider", "type": "text"},
                        {"key": "model", "type": "text"},
                        {"key": "api_key", "type": "password", "sensitive": True},
                        {"key": "base_url", "type": "text"},
                        {"key": "endpoint_url", "type": "text"},
                        {"key": "target_lang", "type": "text"},
                    ],
                },
                {"id": "codex_global", "title": "Codex Global", "restart_required": True},
                {"id": "library_defaults", "title": "Library Defaults", "restart_required": False},
            ],
            "version": 1,
        }

    def get_all(self) -> dict[str, Any]:
        return {
            "schema": self.get_schema(),
            "settings": {
                "pipeline": self._get_pipeline_category(),
                "llm_providers": self._chat_service.get_provider_config(),
                "translation": self._chat_service.get_translation_provider_config(),
                "codex_global": self._chat_service.get_codex_config(),
                "library_defaults": self._get_library_defaults(),
            },
            "updated_at": self._read_store().get("updated_at", ""),
        }

    def update_category(self, category: str, body: dict[str, Any]) -> dict[str, Any]:
        key = str(category or "").strip().lower()
        payload = body if isinstance(body, dict) else {}
        if key == "pipeline":
            return self._save_pipeline_category(payload)
        if key == "llm_providers":
            return self._chat_service.update_provider_config(payload)
        if key == "translation":
            return self._chat_service.save_translation_provider_config(payload)
        if key == "codex_global":
            return self._chat_service.save_codex_config(payload)
        if key == "library_defaults":
            return self._save_library_defaults(payload)
        raise KeyError(f"unknown_settings_category:{key}")
