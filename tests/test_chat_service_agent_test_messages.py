from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService


def _find_check(payload: dict[str, object], name: str) -> dict[str, object]:
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        return {}
    for item in checks:
        if isinstance(item, dict) and str(item.get("name", "")) == name:
            return item
    return {}


class ChatServiceAgentTestMessages(unittest.TestCase):
    @patch("shutil.which", return_value=None)
    def test_agent_test_suggestions_are_readable_chinese(self, _which_mock) -> None:
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            workspaces_dir = data_dir / "libraries" / "workspaces"
            workspaces_dir.mkdir(parents=True, exist_ok=True)
            settings = Settings(data_dir=data_dir)
            service = ChatService(settings)

            payload = service.test_agent("codex")
            claude_payload = service.test_agent("claude_code")

        cli_check = _find_check(payload, "cli_installed")
        cfg_check = _find_check(payload, "agent_config_file")
        self.assertIn("请点击安装按钮安装 Codex CLI", str(cli_check.get("suggestion", "")))
        self.assertIn("请先在 Agent 设置中保存 provider/model/api_key 配置", str(cfg_check.get("suggestion", "")))
        claude_sdk_check = _find_check(claude_payload, "claude_agent_sdk")
        if not bool(claude_sdk_check.get("passed")):
            self.assertIn("claude-agent-sdk 未安装，请运行 pip install claude-agent-sdk", str(claude_sdk_check.get("suggestion", "")))


    @patch("shutil.which", return_value=None)
    def test_agent_test_mcp_config_probe_can_merge_environment(self, _which_mock) -> None:
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            workspaces_dir = data_dir / "libraries" / "workspaces"
            workspaces_dir.mkdir(parents=True, exist_ok=True)
            (workspaces_dir / ".mcp.json").write_text(
                '{"mcpServers":{"kn_graph":{"command":"definitely-not-a-real-command","args":[],"env":{"KN_TEST":"1"}}}}',
                encoding="utf-8",
            )
            settings = Settings(data_dir=data_dir)
            service = ChatService(settings)

            payload = service.test_agent("codex")

        mcp_check = _find_check(payload, "workspace_mcp_json")
        self.assertNotIn("name 'os' is not defined", str(mcp_check.get("error", "")))


if __name__ == "__main__":
    unittest.main()
