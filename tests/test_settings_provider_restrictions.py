from __future__ import annotations

from pathlib import Path

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService
from kn_graph.services.settings_service import SettingsService


class DummyChatService:
    def get_translation_provider_config(self) -> dict:
        return {}

    def save_translation_provider_config(self, body: dict) -> dict:
        return dict(body)

    def get_agent_settings(self) -> dict:
        return {}

    def save_agent_settings(self, body: dict) -> dict:
        return dict(body)


def test_embedding_settings_only_allow_zhipu(tmp_path: Path) -> None:
    service = SettingsService(Settings(data_dir=tmp_path), DummyChatService())  # type: ignore[arg-type]

    saved = service.update_category(
        "embedding",
        {
            "provider": "deepseek",
            "model": "not-used",
            "api_key": "secret",
            "endpoint_url": "https://example.test/embeddings",
        },
    )

    assert saved["provider"] == "zhipu"
    assert [p["id"] for p in saved["provider_presets"]] == ["zhipu"]


def test_pipeline_agent_backend_only_allows_claude_code(tmp_path: Path) -> None:
    service = SettingsService(Settings(data_dir=tmp_path), DummyChatService())  # type: ignore[arg-type]

    saved = service.update_category("pipeline_agent", {"backend": "codex", "provider": "anthropic"})

    assert saved["backend"] == "claude_code"
    assert saved["reasoning_effort_options"] == {"claude_code": ["low", "medium", "high", "max"]}


def test_agent_settings_only_exposes_and_saves_claude_code(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, workspaces_dir=tmp_path / "workspaces")
    service = ChatService(settings)

    saved = service.save_agent_settings({"current_agent": "codex", "provider": "anthropic"})

    assert saved["current_agent"] == "claude_code"
    assert saved["available_agents"] == ["claude_code"]
