from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage:
    ACCEPTED = "accepted"
    PARSE_PDF = "parse_pdf"
    EXTRACT_ENTITIES = "extract_entities"
    FINALIZE = "finalize"


class PipelineJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str = ""
    status: str = "queued"
    stage: str = "accepted"
    progress: int = 0
    error_code: str = ""
    error_detail: str = ""
    input_path: str = ""
    output_path: str = ""
    options: dict[str, Any] = {}
    result: dict[str, Any] = {}
    requested_cancel: bool = False
    idempotency_key: str = ""
    last_event: str = "accepted"
    created_at: str = ""
    updated_at: str = ""
    file_size: int = 0
    file_hash: str = ""
    library_id: str = ""
    workspace_path: str = ""
    source_job_id: str = ""
    file_name: str = ""
    display_name: str = ""
    status_code: str = ""
    stage_code: str = ""
    stage_label: str = ""
    can_cancel: bool = False
    can_retry: bool = False


class PipelineJobResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str = ""
    status: str = ""
    result: dict[str, Any] = {}


class PipelineSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str = ""
    status: str = "queued"
    library_id: str = ""
    workspace_path: str = ""
    file_name: str = ""
    sse_url: str = ""
    result_url: str = ""


class PipelineBatchSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    library_id: str = ""
    accepted_count: int = 0
    rejected_count: int = 0
    accepted: list[PipelineSubmitResponse] = []
    rejected: list[dict[str, Any]] = []


class PipelineJobsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    jobs: list[PipelineJob] = []
    total: int = 0
    page: int = 1
    page_size: int = 50


class PipelineHealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "ok"
    executor: str = "inline"