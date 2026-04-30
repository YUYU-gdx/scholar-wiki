# Backend Unification Design

> Date: 2026-04-30
> Status: Final
> Scope: Merge two backend services into a single FastAPI application

---

## 1. Problem Statement

The current backend consists of two independent servers:

1. **serve_graph_api.py** (2088 lines) — stdlib `http.server`, handles graph/chats/literatures/workspace/static files on port 8013
2. **serve_async_pipeline_api.py** (1293 lines) — FastAPI, handles PDF pipeline job management on port 8021

Problems:

- **Code duplication**: Both have health checks, SSE implementations, request parsing
- **No type safety**: serve_graph_api.py uses manual dict parsing, no Pydantic
- **Two ports**: Consumers need proxy config for two ports; Electron shell needs to start two processes
- **Monolithic files**: 2088 lines in a single file with all concerns interleaved
- **No shared models**: No backend schema to validate request/response types against
- **Inconsistent patterns**: Two different server frameworks with two different coding styles

## 2. Architecture Decision

**Merge into a single FastAPI application**, following the pattern of Zotero 7's architecture (single FastAPI server + optional background worker).

### Rationale

- Single port, single entry point, single `uvicorn` process
- Pydantic models for all request/response types
- Router-based modular code, replacing two 1000+ line monoliths
- Celery worker remains optional for async pipeline tasks
- SSE unified via `sse-starlette`

### What stays

- All URL paths remain identical (`/graph/*`, `/chat/*`, `/v1/jobs/*`, etc.)
- Celery worker runs as a separate process when needed
- MCP server (`kn_mcp_server.py`) unchanged — it's a stdin/stdout process, not HTTP
- `frontend_legacy/` preserved as backup, not modified

### What gets deleted

- `serve_graph_api.py` — replaced by `kn_graph` package
- `serve_async_pipeline_api.py` — replaced by `kn_graph` package

## 3. Project Structure

```
src/kn_graph/                   ← New package root
├── __init__.py
├── __main__.py                 ← `python -m kn_graph serve` / `python -m kn_graph worker`
├── app.py                      ← FastAPI app factory, mounts all routers
├── config.py                   ← Pydantic Settings (ports, DB URLs, API keys)
├── routers/
│   ├── __init__.py
│   ├── graph.py                ← /graph/*, /paper/{id}, /variable/{id}
│   ├── chat.py                 ← /chat/sessions/*, /chat/codex/*, /chat/provider-*
│   ├── literature.py           ← /literature/*
│   ├── pipeline.py             ← /v1/pipeline/*, /v1/jobs/*
│   ├── workspace.py            ← /api/v2/workspace/*
│   └── static.py               ← /frontend/* static file serving
├── models/
│   ├── __init__.py
│   ├── graph.py                ← Pydantic request/response models
│   ├── chat.py
│   ├── literature.py
│   ├── pipeline.py
│   └── workspace.py
├── services/
│   ├── __init__.py
│   ├── graph_service.py        ← Business logic (extracted from handlers)
│   ├── chat_service.py
│   ├── literature_service.py
│   ├── pipeline_service.py
│   └── workspace_service.py
└── workers/
    └── celery_app.py           ← Celery configuration + task definitions
```

### Module responsibilities

| Module | Responsibility | Depends on |
|--------|---------------|-----------|
| `config.py` | Environment variables, defaults, validation | Pydantic Settings |
| `app.py` | FastAPI app factory, CORS, routers, lifespan | All routers, config |
| `routers/*` | HTTP request/response handling only | Services, Models |
| `models/*` | Pydantic V2 schemas, no business logic | — |
| `services/*` | Business logic, data access, external API calls | Config, Models |
| `workers/` | Celery task definitions | Services, Models |

### Entry points

```bash
# Start the unified API server
uv run python -m kn_graph serve --port 8013

# Start Celery worker (optional, for async pipeline tasks)
uv run python -m kn_graph worker

# Start MCP server (unchanged)
uv run python scripts/smj_pipeline/kn_mcp_server.py
```

## 4. API Route Mapping

All existing URL paths are preserved. Routes are grouped by domain:

### Graph & Paper & Variable (from serve_graph_api.py → `routers/graph.py`)

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/graph/overview` | `get_overview` |
| GET | `/graph/full` | `get_full_graph` |
| GET | `/graph/search` | `search_graph` |
| GET | `/graph/neighborhood` | `get_neighborhood` |
| GET | `/paper/{paper_id_or_doi}` | `get_paper` |
| GET | `/variable/{node_id}` | `get_variable` |

### Chat (from serve_graph_api.py → `routers/chat.py`)

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/chat/sessions` | `list_sessions` |
| GET | `/chat/sessions/{session_id}` | `get_session` |
| POST | `/chat/sessions` | `create_session` |
| DELETE | `/chat/sessions/{session_id}` | `delete_session` |
| POST | `/chat/sessions/{session_id}/messages` | `send_message` |
| GET | `/chat/sessions/{session_id}/stream` | `stream_events` |
| POST | `/chat/sessions/{session_id}/restore` | `restore_session` |
| GET/POST | `/chat/codex/config` | `get/save_codex_config` |
| GET | `/chat/codex/health` | `check_codex_health` |
| POST | `/chat/codex/install` | `install_codex` |
| GET | `/chat/codex/preflight` | `preflight_check` |
| GET/POST | `/chat/codex/libraries/{library_id}/config` | `get/save_library_codex_config` |
| POST | `/chat/codex/libraries/{library_id}/skills/bootstrap` | `bootstrap_skills` |
| GET/POST | `/chat/provider-config` | `get/save_provider_config` |
| POST | `/chat/provider-test` | `test_provider` |

### Literature (from serve_graph_api.py → `routers/literature.py`)

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/literature/search` | `search_literature` |
| GET | `/literature/libraries` | `list_libraries` |
| POST | `/literature/import` | `import_manifest` |
| POST | `/literature/answer` | `answer_question` |

### Pipeline (from serve_async_pipeline_api.py → `routers/pipeline.py`)

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/v1/pipeline/health` | `pipeline_health` |
| POST | `/v1/pipeline/parse-extract` | `submit_job` |
| POST | `/v1/pipeline/parse-extract/batch` | `submit_batch` |
| GET | `/v1/jobs` | `list_jobs` |
| GET | `/v1/jobs/{job_id}` | `get_job` |
| GET | `/v1/jobs/{job_id}/result` | `get_result` |
| POST | `/v1/jobs/{job_id}/cancel` | `cancel_job` |
| POST | `/v1/jobs/{job_id}/retry` | `retry_job` |
| GET | `/v1/jobs/{job_id}/events` | `stream_job_events` |

### Workspace (from serve_graph_api.py → `routers/workspace.py`)

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/api/v2/workspace/layouts` | `list_layouts` |
| GET | `/api/v2/workspace/layout` | `get_layout` |
| POST | `/api/v2/workspace/layout` | `save_layout` |

### Health (merged)

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/healthz` | `health_check` (combines both old health checks) |

### Static Files

| Method | Path | New Handler |
|--------|------|-------------|
| GET | `/frontend/*` | FastAPI `StaticFiles` middleware (serves built frontend) |

**Eliminated duplicates**:

- Two health check endpoints → one `/healthz`
- Two SSE implementations → one `sse-starlette`
- Two request parsing systems → one Pydantic validation
- Two CORS configurations → one

## 5. Pydantic Model Strategy

All request/response types use Pydantic V2 models.

### Design rules

- Request models suffixed `Request`
- Response models suffixed `Response` or named by domain (e.g., `GraphOverview`, `PipelineJob`)
- All optional fields use `Optional[T] = None`
- Models contain no business logic — only validation and serialization

### Example

```python
# src/kn_graph/models/chat.py
class CreateSessionRequest(BaseModel):
    title: str
    library_id: str

class CreateSessionResponse(BaseModel):
    id: str
    title: str
    library_id: str
    created_at: Optional[str] = None
```

## 6. Migration Strategy

### Phase 1: Create `kn_graph` package scaffolding

- Create `src/kn_graph/` directory structure
- Add `kn_graph` to `pyproject.toml` as a package
- Implement `app.py` (FastAPI factory), `config.py` (Pydantic Settings)
- Implement all `models/*` (Pydantic schemas)
- Wire up empty `routers/*` that return placeholder responses

### Phase 2: Migrate business logic into `services/*`

- Extract logic from `serve_graph_api.py` handlers into `services/graph_service.py`, `chat_service.py`, etc.
- Extract logic from `serve_async_pipeline_api.py` handlers into `services/pipeline_service.py`
- Unit tests for each service

### Phase 3: Wire routers to services

- Implement all route handlers in `routers/*`
- Each handler calls the corresponding service
- Integration tests against each router

### Phase 4: Replace old servers

- Verify all endpoints work via integration tests
- Update `pyproject.toml` scripts
- Delete `serve_graph_api.py` and `serve_async_pipeline_api.py`
- Update Electron shell to start single process

## 7. Non-Goals (Out of Scope)

- Frontend development (UI components, pages, frameworks)
- Authentication / authorization (security audit is separate)
- Database migration (PostgreSQL schema stays as-is)
- MCP server changes (it's not HTTP)
- Performance optimization beyond framework unification

## 8. Success Criteria

1. All 42 API endpoints respond identically to current behavior
2. Single `uvicorn` process serves all routes
3. All Pydantic models define every request/response type
4. `python -m kn_graph serve --port 8013` replaces both old scripts
5. `python -m kn_graph worker` starts Celery worker (when needed)
6. All existing tests pass
7. No duplicate code between former services