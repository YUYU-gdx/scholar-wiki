from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kn_graph.config import Settings
from kn_graph.routers.settings import create_router
from kn_graph.services.settings_service import SettingsService


class DummyChatService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.translation_calls: list[dict] = []

    def test_provider(self, provider: str, model: str = "", options: dict | None = None, prompt: str = "") -> dict:
        self.calls.append({"provider": provider, "model": model, "options": dict(options or {}), "prompt": prompt})
        return {"ok": True, "provider": provider, "model": model, "response_preview": "OK"}

    def translate_text(self, **kwargs) -> dict:
        self.translation_calls.append(dict(kwargs))
        return {"translated_text": "OK", "provider": kwargs.get("provider", ""), "model": kwargs.get("model", "")}

    def get_translation_provider_config(self) -> dict:
        return {}

    def save_translation_provider_config(self, body: dict) -> dict:
        return dict(body)

    def get_agent_settings(self) -> dict:
        return {}

    def save_agent_settings(self, body: dict) -> dict:
        return dict(body)


class DummyResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


@pytest.fixture()
def service(tmp_path: Path) -> tuple[SettingsService, DummyChatService]:
    settings = Settings(data_dir=tmp_path, workspaces_dir=tmp_path / "workspaces")
    chat = DummyChatService()
    return SettingsService(settings, chat), chat


class DummyRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_turn(self, query: str, workdir: str, library_id: str = "", runtime_overrides: dict | None = None) -> dict:
        self.calls.append({"query": query, "workdir": workdir, "library_id": library_id, "runtime_overrides": runtime_overrides})
        return {"answer": "OK"}


def test_pipeline_agent_key_test_uses_claude_code_runner_without_saving(
    monkeypatch: pytest.MonkeyPatch,
    service: tuple[SettingsService, DummyChatService],
) -> None:
    settings_service, chat = service
    runner = DummyRunner()
    built: list[dict] = []

    def fake_build_runner(backend: str, agent_config: dict) -> DummyRunner:
        built.append({"backend": backend, "agent_config": dict(agent_config)})
        return runner

    monkeypatch.setattr(settings_service, "_build_agent_runner", fake_build_runner)

    result = settings_service.test_api_key(
        "pipeline_agent",
        {
            "backend": "codex",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "draft-secret",
            "base_url": "https://api.deepseek.com",
        },
    )

    assert result["ok"] is True
    assert chat.calls == []
    assert built == [{
        "backend": "claude_code",
        "agent_config": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "draft-secret",
            "base_url": "https://api.deepseek.com",
            "reasoning_effort": "",
        },
    }]
    assert runner.calls[0]["query"] == "Reply with OK only."
    assert not (settings_service._store_path).exists()


def test_embedding_key_test_sends_embedding_request(monkeypatch: pytest.MonkeyPatch, service: tuple[SettingsService, DummyChatService]) -> None:
    settings_service, _chat = service
    calls: list[dict] = []

    def fake_post(url: str, **kwargs) -> DummyResponse:
        calls.append({"url": url, **kwargs})
        return DummyResponse(200, {"data": [{"embedding": [0.1, 0.2]}]})

    monkeypatch.setattr("kn_graph.services.literature_service.requests.post", fake_post)

    result = settings_service.test_api_key(
        "embedding",
        {
            "provider": "zhipu",
            "model": "embedding-3",
            "api_key": "emb-secret",
            "endpoint_url": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        },
    )

    assert result["ok"] is True
    assert calls[0]["url"] == "https://open.bigmodel.cn/api/paas/v4/embeddings"
    assert calls[0]["headers"]["Authorization"] == "Bearer emb-secret"
    assert calls[0]["json"] == {"model": "embedding-3", "input": ["connection test"]}


def test_mineru_key_test_sends_file_url_request(monkeypatch: pytest.MonkeyPatch, service: tuple[SettingsService, DummyChatService]) -> None:
    settings_service, _chat = service
    calls: list[dict] = []

    def fake_post(url: str, **kwargs) -> DummyResponse:
        calls.append({"url": url, **kwargs})
        return DummyResponse(200, {"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload.example"]}})

    monkeypatch.setattr("kn_graph.services.mineru_batch.requests.post", fake_post)

    result = settings_service.test_api_key("pipeline", {"mineru_api_key": "mineru-secret"})

    assert result["ok"] is True
    assert calls[0]["url"] == "https://mineru.net/api/v4/file-urls/batch"
    assert calls[0]["headers"]["Authorization"] == "Bearer mineru-secret"
    assert calls[0]["json"]["files"][0]["data_id"] == "settings-api-key-test"


def test_key_test_rejects_missing_key(service: tuple[SettingsService, DummyChatService]) -> None:
    settings_service, _chat = service

    result = settings_service.test_api_key("translation", {"provider": "deepseek", "api_key": ""})

    assert result["ok"] is False
    assert result["error"] == "api_key_required"


def test_translation_key_test_uses_real_translation_path(service: tuple[SettingsService, DummyChatService]) -> None:
    settings_service, chat = service

    result = settings_service.test_api_key(
        "translation",
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "translation-secret",
            "base_url": "https://api.deepseek.com",
            "endpoint_url": "https://api.deepseek.com/v1/chat/completions",
            "target_lang": "zh",
        },
    )

    assert result["ok"] is True
    assert chat.translation_calls == [{
        "text": "Connection test.",
        "target_lang": "zh",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "api_key": "translation-secret",
        "base_url": "https://api.deepseek.com",
        "endpoint_url": "https://api.deepseek.com/v1/chat/completions",
        "compare_by_paragraph": False,
    }]


def test_settings_key_test_route_runs_blocking_test_outside_event_loop() -> None:
    class LoopSensitiveSettingsService:
        def test_api_key(self, category: str, body: dict) -> dict:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return {"ok": True, "category": category, "body": body}
            return {"ok": False, "error": "still_in_event_loop"}

    app = FastAPI()
    app.include_router(create_router(LoopSensitiveSettingsService()))  # type: ignore[arg-type]

    resp = TestClient(app).post(
        "/settings/test-key",
        json={"category": "pipeline_agent", "config": {"api_key": "draft-secret"}},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
