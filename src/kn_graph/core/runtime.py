from __future__ import annotations

import os
from pathlib import Path


JOB_IMPORTS_DIRNAME = "imports"
JOB_ROOTS_DIRNAME = "jobs"
JOB_INPUT_DIRNAME = "input"
JOB_PARSE_DIRNAME = "parse"
JOB_EXTRACT_DIRNAME = "extract"
JOB_RESULT_FILENAME = "result.json"

PIPELINE_SQLITE_DEFAULT_PATH = "outputs/workbench/pipeline_jobs.sqlite"

# Weaviate default/fallback order when WEAVIATE_URL is not configured.
WEAVIATE_DEFAULT_PORT_CANDIDATES: tuple[int, ...] = (8080, 8090)
SUPPORTED_SOURCE_SUFFIXES: tuple[str, ...] = (".pdf", ".md", ".txt", ".html", ".htm")
DIRECT_EXTRACT_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".html", ".htm")


def detect_default_storage_root(data_dir: str | Path | None = None) -> Path:
    if data_dir:
        return Path(data_dir).resolve()
    if os.name == "nt":
        return Path(r"D:\KNGraphApp")
    return (Path.home() / ".kn_graph_data").resolve()


def resolve_storage_root(*, require_initialized: bool = True, data_dir: str | Path | None = None) -> Path:
    root = detect_default_storage_root(data_dir=data_dir)
    if require_initialized and not root.exists():
        raise RuntimeError(f"storage_root_not_initialized:{root}")
    return root


def ensure_storage_root(path: Path | str | None = None) -> Path:
    root = Path(path).resolve() if path else detect_default_storage_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "libraries" / "workspaces").mkdir(parents=True, exist_ok=True)
    return root


def build_job_root(workspace_root: Path, job_id: str) -> Path:
    return workspace_root / JOB_IMPORTS_DIRNAME / JOB_ROOTS_DIRNAME / str(job_id).strip()


def build_job_input_path(workspace_root: Path, job_id: str, filename: str) -> Path:
    return build_job_root(workspace_root, job_id) / JOB_INPUT_DIRNAME / filename


def classify_source_suffix(filename: str) -> str:
    suffix = Path(str(filename or "").strip()).suffix.lower()
    if suffix in {".pdf"}:
        return "pdf"
    if suffix in {".md"}:
        return "markdown"
    if suffix in {".txt"}:
        return "text"
    if suffix in {".html", ".htm"}:
        return "html"
    return "other"


def build_source_archive_path(workspace_root: Path, filename: str) -> Path:
    source_type = classify_source_suffix(filename)
    return workspace_root / SOURCE_DIRNAME / source_type / filename


def build_weaviate_base_url_candidates(weaviate_url: str = "") -> list[str]:
    explicit = str(weaviate_url or "").strip()
    if explicit:
        return [explicit.rstrip("/")]
    return [f"http://127.0.0.1:{port}" for port in WEAVIATE_DEFAULT_PORT_CANDIDATES]
