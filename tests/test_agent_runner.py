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

default_codex_config = _MOD.default_codex_config
load_codex_config = _MOD.load_codex_config


class AgentRunnerConfigTest(unittest.TestCase):
    def test_default_config_uses_app_server_args(self) -> None:
        cfg = default_codex_config()
        self.assertIn("app-server", list(cfg.get("app_server_args", [])))
        self.assertNotIn("exec", list(cfg.get("app_server_args", [])))

    def test_load_config_normalizes_legacy_cli_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "codex_runner_config.json"
            payload = {
                "cli_command": "codex",
                "cli_args": ["exec", "--cd", "{workdir}", "{prompt}"],
                "healthcheck_args": ["--version"],
                "timeout_seconds": 120,
                "install_command": "",
                "extra_env": {},
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cfg = load_codex_config(path)
            self.assertEqual(cfg.app_server_command, "codex")
            self.assertIn("app-server", cfg.app_server_args)


if __name__ == "__main__":
    unittest.main()
