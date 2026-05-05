from __future__ import annotations

import json
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "agent_runner.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_agent_runner_for_tests", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load module: {_MODULE_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


class AgentRunnerFactoryTest(unittest.TestCase):
    def test_factory_builds_all_backends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "codex_runner_config.json"
            config_path.write_text(json.dumps({"model": "gpt-5.2"}), encoding="utf-8")
            factory = _MOD.AgentRunnerFactory(codex_config_path=config_path)

            codex_runner = factory.build("codex")
            self.assertEqual(codex_runner.backend, "codex")
            self.assertEqual(codex_runner._codex_bin, "codex")
            self.assertEqual(codex_runner._model, "gpt-5.2")

            claude_runner = factory.build("claude_code")
            self.assertEqual(claude_runner.backend, "claude_code")

    def test_factory_defaults_model_when_config_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nonexistent.json"
            factory = _MOD.AgentRunnerFactory(codex_config_path=config_path)
            codex_runner = factory.build("codex")
            self.assertEqual(codex_runner._model, "gpt-5.2")

    def test_factory_rejects_invalid_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "codex_runner_config.json"
            config_path.write_text("{}", encoding="utf-8")
            factory = _MOD.AgentRunnerFactory(codex_config_path=config_path)
            with self.assertRaises(RuntimeError):
                factory.build("nonexistent")


class CodexRunnerHealthTest(unittest.TestCase):
    def test_health_reports_available_or_reason(self) -> None:
        runner = _MOD.CodexRunner(codex_bin="codex")
        health = runner.health()
        self.assertEqual(health["backend"], "codex")
        self.assertIn("available", health)
        self.assertIn("version", health)


class NotificationToDictTest(unittest.TestCase):
    def test_returns_method_and_params(self) -> None:
        class FakePayload:
            def model_dump(self, **kwargs):
                return {"delta": "hello", "turn_id": "t1"}

        class FakeNotification:
            method = "item/agentMessage/delta"
            payload = FakePayload()

        result = _MOD._notification_to_dict(FakeNotification())
        self.assertEqual(result["method"], "item/agentMessage/delta")
        self.assertEqual(result["params"]["delta"], "hello")


if __name__ == "__main__":
    unittest.main()
