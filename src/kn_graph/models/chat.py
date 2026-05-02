from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    library_id: str = ""


class ChatSession(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = ""
    title: str = ""
    default_mode: str = "agent"
    library_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    deleted_at: Optional[str] = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: str = ""
    session_id: str = ""
    role: str = ""
    mode: str = "agent"
    provider: str = ""
    model: str = ""
    content: str = ""
    citations_json: str = "[]"
    retrieval_json: str = "{}"
    tool_trace_json: str = "[]"
    status: str = "completed"
    error_detail: str = ""
    created_at: str = ""
    updated_at: str = ""
    citations: list[Any] = []
    retrieval: dict[str, Any] = {}
    tool_trace: list[Any] = []
    error_code: str = ""
    error_backend: str = ""


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str = ""
    mode: str = "agent"
    stream: bool = True
    library_id: str = ""
    provider: str = "codex"
    model: str = "codex-local"


class SendMessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = ""
    assistant_message_id: str = ""
    user_message_id: str = ""
    stream_url: str = ""


class DeleteSessionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = ""
    library_id: str = ""
    deleted_at: str = ""
    undo_window_seconds: int = 5
    undo_deadline: str = ""


class RestoreSessionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = ""
    library_id: str = ""
    restored: bool = False
    error: str = ""


class CodexConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_server_command: str = ""
    app_server_args: list[str] = []
    healthcheck_args: list[str] = []
    timeout_seconds: int = 60
    install_command: str = ""
    extra_env: dict[str, str] = {}
    model: str = ""
    approval_policy: str = ""
    sandbox_mode: str = ""
    personality: str = ""
    mcp_servers: list[Any] = []
    config_path: str = ""


class CodexHealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: str = "codex"
    available: bool = False
    reason: str = ""
    version: str = ""


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    check_id: str = ""
    name: str = ""
    passed: bool = False
    stage: str = ""
    backend: str = ""
    code: str = ""
    detail: str = ""
    suggestion: str = ""
    severity: str = ""


class PreflightResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = False
    severity: str = ""
    library_id: str = ""
    summary: str = ""
    checks: list[PreflightCheck] = []
    failed_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    checked_at: str = ""


class ProviderItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    default_model: str = ""
    api_key_env: str = ""
    base_url: str = ""


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_provider: str = ""
    providers: list[ProviderItem] = []
    config_path: str = ""
