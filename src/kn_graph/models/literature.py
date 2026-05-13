from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class LiteratureLibrary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    library_id: str = ""
    name: str = ""
    workspace_root: str = ""
    paper_count: int = 0
    chunk_count: int = 0
    index_exists: bool = False
    created_at: str = ""
    updated_at: str = ""


class LiteratureSearchParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = ""
    top_k: int = 20
    levels: list[str] = ["sentence"]
    library_id: str = ""
    keyword_weight: float = 0.4
    rag_weight: float = 0.6
    include_expanded_context: bool = True


class LiteratureAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = ""
    top_k: int = 5
    levels: list[str] = ["sentence"]
    library_id: str = ""
    keyword_weight: float = 0.4
    rag_weight: float = 0.6


class LiteratureAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str = ""
    citations: list[Any] = []
    retrieval: dict[str, Any] = {}
    query: str = ""
    library_id: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class LiteratureCreateLibraryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    library_id: str = ""
    workspace_root: str = ""
    set_default: bool = True


class LiteratureSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = ""
    library_id: str = ""
    top_k: int = 20
    levels: list[str] = ["sentence"]
    keyword_hits: list[Any] = []
    rag_hits: list[Any] = []
    merged_hits: list[Any] = []
    degraded: bool = False
    degraded_reason: str = ""


# ── Zotero import models ──────────────────────────────────────────────


class ZoteroScanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data_dir: str = ""


class ZoteroImportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data_dir: str = ""
    item_ids: list[int] = []
    library_id: str = ""


class ZoteroImportResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    job_ids: list[str] = []
    count: int = 0
