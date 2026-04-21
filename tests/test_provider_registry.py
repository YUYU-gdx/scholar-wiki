from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "llm" / "provider_registry.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_provider_registry_test_module", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

ProviderRegistry = _MOD.ProviderRegistry


class ProviderRegistryTest(unittest.TestCase):
    def test_alias_resolution_and_provider_list(self) -> None:
        registry = ProviderRegistry()
        names = set(registry.list_provider_names())
        self.assertIn("zhipu", names)
        self.assertIn("glm", names)
        self.assertIn("deepseek", names)
        self.assertEqual(registry.resolve_provider_id("glm"), "zhipu")

    def test_create_message_client_accepts_explicit_api_key(self) -> None:
        registry = ProviderRegistry()
        client = registry.create_message_client(
            provider="deepseek",
            model="deepseek-chat",
            options={"api_key": "dummy", "base_url": "https://api.example.com/v1/chat/completions"},
        )
        self.assertTrue(hasattr(client, "complete_messages"))
        self.assertTrue(hasattr(client, "stream_messages"))

    def test_create_message_client_missing_key_raises(self) -> None:
        registry = ProviderRegistry()
        with self.assertRaises(RuntimeError):
            registry.create_message_client(provider="deepseek", model="deepseek-chat")

    def test_update_config_normalizes_models_and_default_model(self) -> None:
        payload = {
            "default_provider": "demo",
            "providers": [
                {
                    "id": "demo",
                    "type": "openai_compatible",
                    "api_key_env": "DEMO_API_KEY",
                    "default_model": "demo-chat",
                    "models": ["demo-chat", "demo-reasoner", "demo-chat"],
                    "base_url": "https://api.example.com/v1/chat/completions",
                    "aliases": ["Demo", "demo"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "providers.json"
            config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            registry = ProviderRegistry(config_path=config_path)
            saved = registry.update_config(payload)
            self.assertEqual(saved["default_provider"], "demo")
            self.assertEqual(saved["providers"][0]["default_model"], "demo-chat")
            self.assertEqual(saved["providers"][0]["models"], ["demo-chat", "demo-reasoner"])
            self.assertEqual(saved["providers"][0]["aliases"], ["demo"])


if __name__ == "__main__":
    unittest.main()
