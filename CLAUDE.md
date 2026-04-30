# KN Graph

Knowledge graph construction and QA platform for academic literature, focused on supply chain research.

## Quick Start

```bash
# Start the main API server (graph + chat + literature + workspace)
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013 --views-json outputs/.../graph_views.json --allow-non-supply-chain

# Start the async pipeline API (PDF parsing + extraction jobs)
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --host 127.0.0.1 --port 8021

# Start desktop launcher (starts both + opens browser)
uv run python scripts/smj_pipeline/app_launcher.py
```

## Project Structure

```
kn_gragh/
├── src/kn_graph/              ← Backend package (refactoring in progress)
├── scripts/smj_pipeline/      ← Current backend entry points (to be replaced)
│   ├── serve_graph_api.py      ← Main API server (port 8013)
│   ├── serve_async_pipeline_api.py ← Async pipeline API (port 8021)
│   └── kn_mcp_server.py       ← MCP tool server (stdin/stdout)
├── config/                    ← LLM provider config
├── prompt/                    ← Extraction prompt templates
├── outputs/                   ← Runtime artifacts
├── tests/                     ← Tests
├── frontend_legacy/           ← Archived frontend (frozen, do not modify)
└── docs/                      ← Documentation
```

## Documentation

- Project spec index: `docs/project_spec_index.md`
- Graph API spec: `docs/api.md`
- Async Pipeline API spec: `docs/async_pipeline_api.md`
- Data model spec: `docs/data_model.md`
- Backend unification design: `docs/superpowers/specs/2026-04-30-backend-unification-design.md`

## Configuration

| Environment Variable | Purpose | Default |
|---------------------|---------|---------|
| `KN_GRAPH_PORT` | Main API port | `8013` |
| `KN_ASYNC_PIPELINE_PORT` | Pipeline API port | `8021` |
| `CHAT_STORE_DSN` | Chat storage DSN | In-memory |
| `PIPELINE_JOB_STORE_DSN` | Pipeline job store DSN | SQLite |
| `PIPELINE_EXECUTOR` | Executor type | `inline` |
| `PIPELINE_REDIS_URL` | Celery broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | Zhipu API key | — |
| `NVIDIA_API_KEY` | NVIDIA API key | — |
| `LLM_PROVIDER_CONFIG_PATH` | LLM config path | `config/llm_providers.json` |
| `WEAVIATE_URL` | Weaviate address | `http://127.0.0.1:8090` |

## Testing

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## Refactoring Status

- **In progress**: Backend unification into single `src/kn_graph/` FastAPI package. See design doc for details.
- **Frozen**: `frontend_legacy/` is archived and must not be modified.
- **Prohibited**: Do not create or modify any `frontend/` directory content.

## LLM Provider Configuration

- Config file: `config/llm_providers.json`
- Chat, async pipeline, and extraction all use the same provider registry: `scripts/smj_pipeline/llm/provider_registry.py`
- Override config path: `set LLM_PROVIDER_CONFIG_PATH=path/to/config.json`