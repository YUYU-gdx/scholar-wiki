from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kn_graph.config import Settings
from kn_graph.services.settings_service import SettingsService


class _FakeChatService:
    def __init__(self) -> None:
        self.provider = {"default_provider": "zhipu", "providers": []}
        self.translation = {"provider": "deepseek", "api_key": "", "model": "deepseek-v4-flash", "base_url": "", "endpoint_url": "", "target_lang": "zh"}
        self.codex = {"model": "codex-local"}

    def get_provider_config(self):
        return self.provider

    def update_provider_config(self, payload):
        self.provider = dict(payload)
        return self.provider

    def get_translation_provider_config(self):
        return self.translation

    def save_translation_provider_config(self, payload):
        self.translation = {**self.translation, **payload}
        return self.translation

    def get_codex_config(self):
        return self.codex

    def save_codex_config(self, payload):
        self.codex = {**self.codex, **payload}
        return self.codex


class TestSettingsService(unittest.TestCase):
    def test_pipeline_validation_clamps_and_normalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(data_dir=Path(tmp))
            svc = SettingsService(settings, _FakeChatService())
            saved = svc.update_category("pipeline", {"executor": "INLINE", "max_poll_seconds": 3, "poll_interval_seconds": 999, "max_retries": -4})
            self.assertEqual(saved["executor"], "inline")
            self.assertEqual(saved["max_poll_seconds"], 30)
            self.assertEqual(saved["poll_interval_seconds"], 120.0)
            self.assertEqual(saved["max_retries"], 0)

    def test_pipeline_validation_rejects_unknown_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(data_dir=Path(tmp))
            svc = SettingsService(settings, _FakeChatService())
            with self.assertRaises(ValueError):
                svc.update_category("pipeline", {"executor": "queue"})

    def test_schema_contains_sensitive_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(data_dir=Path(tmp))
            svc = SettingsService(settings, _FakeChatService())
            schema = svc.get_schema()
            translation = [c for c in schema["categories"] if c["id"] == "translation"][0]
            api_key = [f for f in translation.get("fields", []) if f.get("key") == "api_key"][0]
            self.assertTrue(api_key.get("sensitive"))


if __name__ == "__main__":
    unittest.main()
