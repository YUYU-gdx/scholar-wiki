from __future__ import annotations

from pathlib import Path

import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kn_graph.config import Settings
from kn_graph.services.settings_service import SettingsService
from kn_graph.services.pipeline_runtime import _inject_pipeline_settings, init_pipeline_settings


class _DummyChatService:
    def get_translation_provider_config(self):
        return {}

    def save_translation_provider_config(self, body):
        return body

    def get_agent_settings(self):
        return {}

    def save_agent_settings(self, body):
        return body


def test_pipeline_agent_reasoning_effort_saved_for_codex(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _DummyChatService())  # type: ignore[arg-type]
    out = svc.update_category(
        "pipeline_agent",
        {"backend": "codex", "reasoning_effort": "xhigh"},
    )
    assert out["backend"] == "codex"
    assert out["reasoning_effort"] == "xhigh"


def test_pipeline_agent_reasoning_effort_validation_for_claude(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _DummyChatService())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pipeline_agent.reasoning_effort"):
        svc.update_category(
            "pipeline_agent",
            {"backend": "claude_code", "reasoning_effort": "xhigh"},
        )


def test_pipeline_agent_reasoning_effort_injected_into_pipeline_options(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _DummyChatService())  # type: ignore[arg-type]
    svc.update_category(
        "pipeline_agent",
        {"backend": "codex", "reasoning_effort": "medium"},
    )
    init_pipeline_settings(settings)
    options = _inject_pipeline_settings({})
    assert options.get("pipeline_agent_backend") == "codex"
    assert options.get("pipeline_agent_reasoning_effort") == "medium"
