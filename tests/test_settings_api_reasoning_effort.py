from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kn_graph.config import Settings
from kn_graph.routers import settings as settings_router
from kn_graph.services.settings_service import SettingsService


class _FakeChatService:
    def get_translation_provider_config(self):
        return {}

    def save_translation_provider_config(self, body):
        return body

    def get_agent_settings(self):
        return {"current_agent": "codex", "available_agents": ["codex", "claude_code", "gemini_cli"]}

    def save_agent_settings(self, body):
        return body


def test_settings_api_pipeline_agent_reasoning_effort_roundtrip(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _FakeChatService())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(settings_router.create_router(svc))
    client = TestClient(app)

    put_resp = client.put(
        "/settings/pipeline_agent",
        json={
            "backend": "codex",
            "provider": "deepseek",
            "reasoning_effort": "high",
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    put_data = put_resp.json()
    assert put_data.get("ok") is True
    cfg = put_data.get("config", {})
    assert cfg.get("backend") == "codex"
    assert cfg.get("reasoning_effort") == "high"
    assert "xhigh" in (cfg.get("reasoning_effort_options", {}).get("codex", []))

    get_resp = client.get("/settings")
    assert get_resp.status_code == 200, get_resp.text
    payload = get_resp.json()
    pa = payload.get("settings", {}).get("pipeline_agent", {})
    assert pa.get("backend") == "codex"
    assert pa.get("reasoning_effort") == "high"
    assert "max" in (pa.get("reasoning_effort_options", {}).get("claude_code", []))


def test_settings_api_agent_template_read_write(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _FakeChatService())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(settings_router.create_router(svc))
    client = TestClient(app)

    get_resp = client.get("/settings/agent-templates/pipeline_skill")
    assert get_resp.status_code == 200, get_resp.text
    get_data = get_resp.json()
    assert get_data.get("target") == "pipeline_skill"
    assert "content" in get_data


def test_settings_api_skill_template_write_forbidden(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _FakeChatService())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(settings_router.create_router(svc))
    client = TestClient(app)

    original_resp = client.get("/settings/agent-templates/pipeline_skill")
    assert original_resp.status_code == 200, original_resp.text
    original = str(original_resp.json().get("content", ""))

    try:
        put_resp = client.put(
            "/settings/agent-templates/pipeline_skill",
            json={"content": "# test\nhello"},
        )
        assert put_resp.status_code == 200, put_resp.text
        body = put_resp.json()
        assert body.get("target") == "pipeline_skill"
        assert str(body.get("content", "")).startswith("# test")
    finally:
        restore_resp = client.put(
            "/settings/agent-templates/pipeline_skill",
            json={"content": original},
        )
        assert restore_resp.status_code == 200, restore_resp.text


def test_settings_api_agent_md_uses_template_path(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _FakeChatService())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(settings_router.create_router(svc))
    client = TestClient(app)

    original_resp = client.get("/settings/agent-templates/claude_md")
    assert original_resp.status_code == 200, original_resp.text
    original = str(original_resp.json().get("content", ""))

    try:
        put_resp = client.put(
            "/settings/agent-templates/claude_md",
            json={"content": "# CLAUDE template\nok"},
        )
        assert put_resp.status_code == 200, put_resp.text
        put_data = put_resp.json()
        assert "skills/templates/agent-docs/CLAUDE.md" in str(put_data.get("path", "")).replace("\\", "/")
    finally:
        restore_resp = client.put(
            "/settings/agent-templates/claude_md",
            json={"content": original},
        )
        assert restore_resp.status_code == 200, restore_resp.text


def test_settings_api_agent_md_shares_claude_template_path(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    svc = SettingsService(settings, _FakeChatService())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(settings_router.create_router(svc))
    client = TestClient(app)

    a = client.get("/settings/agent-templates/claude_md")
    b = client.get("/settings/agent-templates/agent_md")
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    pa = str(a.json().get("path", "")).replace("\\", "/")
    pb = str(b.json().get("path", "")).replace("\\", "/")
    assert pa.endswith("/skills/templates/agent-docs/CLAUDE.md")
    assert pb == pa
