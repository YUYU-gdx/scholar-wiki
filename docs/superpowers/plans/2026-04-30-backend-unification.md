# Backend Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge two backend servers into a single FastAPI application under `src/kn_graph/`.

**Architecture:** Single `uvicorn` process serves all routes. FastAPI app factory in `app.py` mounts domain routers. Business logic extracted into service classes. Pydantic V2 models for all request/response types. Celery worker runs as separate optional process.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic V2, uvicorn, sse-starlette, Celery (optional)

**Design Spec:** `docs/superpowers/specs/2026-04-30-backend-unification-design.md`

---

## File Structure

### New files (to create)

```
src/kn_graph/__init__.py                     ← Package init, version
src/kn_graph/__main__.py                     ← CLI entry point (serve, worker)
src/kn_graph/app.py                          ← FastAPI app factory
src/kn_graph/config.py                       ← Pydantic Settings
src/kn_graph/routers/__init__.py
src/kn_graph/routers/graph.py                ← /graph/*, /paper/*, /variable/*
src/kn_graph/routers/chat.py                 ← /chat/*
src/kn_graph/routers/literature.py           ← /literature/*
src/kn_graph/routers/pipeline.py             ← /v1/pipeline/*, /v1/jobs/*
src/kn_graph/routers/workspace.py            ← /api/v2/workspace/*
src/kn_graph/routers/static_files.py         ← /frontend/* static serving
src/kn_graph/models/__init__.py
src/kn_graph/models/graph.py                 ← Pydantic models for graph domain
src/kn_graph/models/chat.py                  ← Pydantic models for chat domain
src/kn_graph/models/literature.py            ← Pydantic models for literature domain
src/kn_graph/models/pipeline.py              ← Pydantic models for pipeline domain
src/kn_graph/models/workspace.py             ← Pydantic models for workspace domain
src/kn_graph/services/__init__.py
src/kn_graph/services/graph_service.py       ← Business logic extracted from serve_graph_api.py
src/kn_graph/services/chat_service.py       ← Business logic for chat
src/kn_graph/services/literature_service.py  ← Business logic for literature
src/kn_graph/services/pipeline_service.py    ← Business logic for pipeline jobs
src/kn_graph/services/workspace_service.py   ← Business logic for workspace layouts
src/kn_graph/workers/__init__.py
src/kn_graph/workers/celery_app.py           ← Celery configuration + task definitions
```

### Modified files

```
pyproject.toml                              ← Add kn_graph package, add pydantic + pydantic-settings deps
```

### Deleted files (Phase 4 only, after verification)

```
scripts/smj_pipeline/serve_graph_api.py     ← Replaced by kn_graph package
scripts/smj_pipeline/serve_async_pipeline_api.py ← Replaced by kn_graph package
```

---

## Task 1: Package Scaffolding + Config

**Files:**
- Create: `src/kn_graph/__init__.py`
- Create: `src/kn_graph/__main__.py`
- Create: `src/kn_graph/app.py`
- Create: `src/kn_graph/config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add kn_graph package and dependencies to pyproject.toml**

Add `pydantic>=2.7`, `pydantic-settings>=2.3` to dependencies. Add `[tool.setuptools.packages.find]` section pointing to `src/`.

```toml
# In dependencies list, add:
"pydantic>=2.7.0",
"pydantic-settings>=2.3.0",

# Add at end of file:
[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create `src/kn_graph/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create `src/kn_graph/config.py`**

Pydantic Settings class that reads environment variables. Must match all existing env vars used by both servers:

```python
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8013

    # Graph data
    views_json: Optional[Path] = None
    allow_non_supply_chain: bool = False

    # Chat
    chat_store_dsn: str = ""

    # Pipeline
    pipeline_job_store_dsn: str = "sqlite:///jobs.db"
    pipeline_executor: str = "inline"
    pipeline_redis_url: str = "redis://127.0.0.1:6379/0"

    # Literature / Weaviate
    weaviate_url: str = "http://127.0.0.1:8090"

    # LLM
    llm_provider_config_path: str = "config/llm_providers.json"

    model_config = {"env_prefix": "KN_GRAPH_", "env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 4: Create `src/kn_graph/app.py`**

FastAPI app factory that includes all routers and adds CORS middleware:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kn_graph.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="KN Graph API",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers will be included in later tasks
    # from kn_graph.routers import graph, chat, literature, pipeline, workspace, static_files
    # app.include_router(graph.router)
    # app.include_router(chat.router)
    # app.include_router(literature.router)
    # app.include_router(pipeline.router)
    # app.include_router(workspace.router)
    # app.include_router(static_files.router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Create `src/kn_graph/__main__.py`**

CLI entry point with `serve` and `worker` subcommands:

```python
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="KN Graph")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8013)
    serve_parser.add_argument("--views-json", type=str, default=None)
    serve_parser.add_argument("--allow-non-supply-chain", action="store_true")

    sub.add_parser("worker", help="Start the Celery worker")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from kn_graph.config import Settings

        settings = Settings(
            host=args.host,
            port=args.port,
            views_json=args.views_json,
            allow_non_supply_chain=args.allow_non_supply_chain,
        )
        from kn_graph.app import create_app
        app = create_app(settings)
        uvicorn.run(app, host=settings.host, port=settings.port)

    elif args.command == "worker":
        from kn_graph.workers.celery_app import celery_app
        celery_app.worker_main(sys.argv[2:])

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run `uv run python -m kn_graph serve --help` to verify entry point works**

Expected: Help message output showing `serve` and `worker` subcommands.

- [ ] **Step 7: Run `uv run python -c "from kn_graph.config import Settings; print(Settings())"` to verify config**

Expected: Settings printed with default values.

- [ ] **Step 8: Commit**

```bash
git add src/kn_graph/ pyproject.toml
git commit -m "feat: scaffold kn_graph package with FastAPI app factory and Settings"
```

---

## Task 2: Pydantic Models

**Files:**
- Create: `src/kn_graph/models/__init__.py`
- Create: `src/kn_graph/models/graph.py`
- Create: `src/kn_graph/models/chat.py`
- Create: `src/kn_graph/models/literature.py`
- Create: `src/kn_graph/models/pipeline.py`
- Create: `src/kn_graph/models/workspace.py`

All model definitions must be extracted from the existing handler code. Each model mirrors the request/response shapes documented in the design spec.

- [ ] **Step 1: Create `src/kn_graph/models/__init__.py`** — re-exports all models.

- [ ] **Step 2: Create `src/kn_graph/models/graph.py`** — models for `/graph/*`, `/paper/*`, `/variable/*` endpoints. Must include: `GraphOverview`, `GraphFull`, `GraphNode`, `GraphEdge`, `ModerationLink`, `InteractionLink`, `IsolatedNode`, `GraphSearchParams`, `GraphSearchResponse`, `SearchResult`, `NeighborhoodParams`, `NeighborhoodResponse`, `PaperDetail`, `VariableDetail`.

- [ ] **Step 3: Create `src/kn_graph/models/chat.py`** — models for `/chat/*` endpoints. Must include: `CreateSessionRequest`, `ChatSession`, `SendMessageRequest`, `SendMessageResponse`, `SSEEvent`, `CodexConfig`, `CodexHealthResponse`, `PreflightCheck`, `PreflightResponse`, `ProviderConfig`.

- [ ] **Step 4: Create `src/kn_graph/models/literature.py`** — models for `/literature/*`. Must include: `LiteratureLibrary`, `LiteratureSearchParams`, `LiteratureAnswerRequest`, `LiteratureAnswerResponse`, `LiteratureImportRequest`.

- [ ] **Step 5: Create `src/kn_graph/models/pipeline.py`** — models for `/v1/*`. Must include: `PipelineJob`, `PipelineJobsResponse`, `PipelineJobResult`, `PipelineSubmitResponse`, `PipelineBatchSubmitResponse`, `JobStatus`, `JobStage`.

- [ ] **Step 6: Create `src/kn_graph/models/workspace.py`** — models for `/api/v2/workspace/*`. Must include: `WorkspaceLayout`, `WorkspaceLayoutList`.

- [ ] **Step 7: Run `uv run python -c "from kn_graph.models import *; print('Models OK')"`**

Expected: "Models OK" with no import errors.

- [ ] **Step 8: Commit**

```bash
git add src/kn_graph/models/
git commit -m "feat: add Pydantic V2 models for all API domains"
```

---

## Task 3: Service Layer — Graph, Workspace, Literature

**Files:**
- Create: `src/kn_graph/services/__init__.py`
- Create: `src/kn_graph/services/graph_service.py`
- Create: `src/kn_graph/services/workspace_service.py`
- Create: `src/kn_graph/services/literature_service.py`

These services wrap the existing business logic from `serve_graph_api.py`. They import from the existing modules under `scripts/smj_pipeline/` during migration (to be refactored to proper imports later).

- [ ] **Step 1: Create `src/kn_graph/services/__init__.py`**

- [ ] **Step 2: Create `src/kn_graph/services/graph_service.py`** — extract graph data loading, search, neighborhood BFS, paper/variable detail from `serve_graph_api.py` lines handling `/graph/*`, `/paper/*`, `/variable/*`. The service class takes `Settings` and graph data path in constructor.

- [ ] **Step 3: Create `src/kn_graph/services/workspace_service.py`** — extract workspace layout CRUD from `serve_graph_api.py`. Wraps `WorkspaceLayoutStore`.

- [ ] **Step 4: Create `src/kn_graph/services/literature_service.py`** — extract literature search/answer/import from `serve_graph_api.py`. Wraps `LiteratureService`.

- [ ] **Step 5: Run `uv run python -c "from kn_graph.services.graph_service import GraphService; print('GraphService OK')"` and similar for others**

Expected: No import errors.

- [ ] **Step 6: Commit**

```bash
git add src/kn_graph/services/
git commit -m "feat: add graph, workspace, literature service layer"
```

---

## Task 4: Service Layer — Chat + Pipeline

**Files:**
- Create: `src/kn_graph/services/chat_service.py`
- Create: `src/kn_graph/services/pipeline_service.py`

- [ ] **Step 1: Create `src/kn_graph/services/chat_service.py`** — extract chat session management, message dispatch, SSE streaming, Codex config, provider config from `serve_graph_api.py`. Wraps `ChatService`.

- [ ] **Step 2: Create `src/kn_graph/services/pipeline_service.py`** — extract job store, job lifecycle, submit, cancel, retry logic from `serve_async_pipeline_api.py`. Wraps `InMemoryJobStore`, `SqliteJobStore`, and Celery dispatcher.

- [ ] **Step 3: Run `uv run python -c "from kn_graph.services.chat_service import ChatService; from kn_graph.services.pipeline_service import PipelineService; print('Services OK')"`**

Expected: No import errors.

- [ ] **Step 4: Commit**

```bash
git add src/kn_graph/services/
git commit -m "feat: add chat and pipeline service layer"
```

---

## Task 5: Routers — Graph, Workspace, Literature, Health

**Files:**
- Create: `src/kn_graph/routers/__init__.py`
- Create: `src/kn_graph/routers/graph.py`
- Create: `src/kn_graph/routers/workspace.py`
- Create: `src/kn_graph/routers/literature.py`
- Modify: `src/kn_graph/app.py` (uncomment router includes)

- [ ] **Step 1: Create `src/kn_graph/routers/__init__.py`**

- [ ] **Step 2: Create `src/kn_graph/routers/graph.py`** — FastAPI `APIRouter` with all `/graph/*`, `/paper/*`, `/variable/*` endpoints using Pydantic models and `GraphService`.

- [ ] **Step 3: Create `src/kn_graph/routers/workspace.py`** — `/api/v2/workspace/*` endpoints using `WorkspaceService`.

- [ ] **Step 4: Create `src/kn_graph/routers/literature.py`** — `/literature/*` endpoints using `LiteratureService`.

- [ ] **Step 5: Update `src/kn_graph/app.py`** — uncomment and activate the router includes for graph, workspace, literature. Add `/healthz` that also checks pipeline readiness.

- [ ] **Step 6: Start the server and test endpoints**

```bash
uv run python -m kn_graph serve --port 8013 --views-json outputs/smj_supply_chain_batch/supply_chain_theme_extract_20260420_160040/graph_views.json --allow-non-supply-chain
```

Test: `curl http://127.0.0.1:8013/healthz` → `{"status":"ok"}`

Test: `curl http://127.0.0.1:8013/graph/overview` → JSON response

- [ ] **Step 7: Commit**

```bash
git add src/kn_graph/routers/ src/kn_graph/app.py
git commit -m "feat: add graph, workspace, literature routers"
```

---

## Task 6: Routers — Chat, Pipeline

**Files:**
- Create: `src/kn_graph/routers/chat.py`
- Create: `src/kn_graph/routers/pipeline.py`
- Modify: `src/kn_graph/app.py` (add remaining routers)

- [ ] **Step 1: Create `src/kn_graph/routers/chat.py`** — all `/chat/*` endpoints including SSE streaming via `sse-starlette`, Codex config, provider config. Uses `ChatService`.

- [ ] **Step 2: Create `src/kn_graph/routers/pipeline.py`** — all `/v1/*` endpoints including SSE for job events, file upload via `UploadFile`. Uses `PipelineService`.

- [ ] **Step 3: Update `src/kn_graph/app.py`** — add chat and pipeline router includes.

- [ ] **Step 4: Start the server and test chat and pipeline endpoints**

```bash
uv run python -m kn_graph serve --port 8013 --views-json outputs/smj_supply_chain_batch/supply_chain_theme_extract_20260420_160040/graph_views.json --allow-non-supply-chain
```

Test: `curl http://127.0.0.1:8013/chat/sessions?library_id=supply_chain` → JSON

Test: `curl http://127.0.0.1:8013/v1/pipeline/health` → `{"status":"ok","executor":"inline"}`

- [ ] **Step 5: Commit**

```bash
git add src/kn_graph/routers/ src/kn_graph/app.py
git commit -m "feat: add chat and pipeline routers"
```

---

## Task 7: Static File Serving + Workers

**Files:**
- Create: `src/kn_graph/routers/static_files.py`
- Create: `src/kn_graph/workers/__init__.py`
- Create: `src/kn_graph/workers/celery_app.py`
- Modify: `src/kn_graph/app.py` (add static files router)

- [ ] **Step 1: Create `src/kn_graph/routers/static_files.py`** — FastAPI `StaticFiles` mount for `/frontend` path, serving from `frontend_legacy/` directory. Fall back to `index.html` for SPA routes (workbench, chat).

- [ ] **Step 2: Create `src/kn_graph/workers/__init__.py`**

- [ ] **Step 3: Create `src/kn_graph/workers/celery_app.py`** — extract Celery configuration from `serve_async_pipeline_api.py`. Define task signatures for parse-extract pipeline.

- [ ] **Step 4: Update `src/kn_graph/app.py`** — add static files mount and include all routers.

- [ ] **Step 5: Test static file serving** — `curl http://127.0.0.1:8013/frontend/` → returns HTML.

- [ ] **Step 6: Commit**

```bash
git add src/kn_graph/routers/static_files.py src/kn_graph/workers/ src/kn_graph/app.py
git commit -m "feat: add static file serving and Celery worker"
```

---

## Task 8: Integration Testing + Cleanup

**Files:**
- Modify: existing test files to point at new unified server
- Delete: `scripts/smj_pipeline/serve_graph_api.py` (only after all tests pass)
- Delete: `scripts/smj_pipeline/serve_async_pipeline_api.py` (only after all tests pass)

- [ ] **Step 1: Run all existing tests to verify no regressions**

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

- [ ] **Step 2: Update test configuration** — any tests that directly import from `serve_graph_api` or `serve_async_pipeline_api` must be updated to import from `kn_graph.app` or `kn_graph.routers.*`.

- [ ] **Step 3: Verify all 42 API endpoints respond correctly** by running integration tests against the unified server on port 8013.

- [ ] **Step 4: Update `scripts/smj_pipeline/app_launcher.py`** — change it to launch `uv run python -m kn_graph serve --port 8013` instead of two separate servers.

- [ ] **Step 5: Delete old server files**

```bash
git rm scripts/smj_pipeline/serve_graph_api.py scripts/smj_pipeline/serve_async_pipeline_api.py
```

- [ ] **Step 6: Run full test suite again**

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: delete legacy server files, unified kn_graph app replaces both"
```