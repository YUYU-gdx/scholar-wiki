from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class WorkspaceLayout(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    layout: dict[str, Any] = {}
    updated_at: str = ""
    storage_mode: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class WorkspaceLayoutList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    layouts: list[dict[str, Any]] = []
    storage_mode: str = ""
    degraded: bool = False
    degraded_reason: str = ""