# Closed-Loop Pipeline Design

**Date**: 2026-05-01
**Status**: Draft

## Problem

Currently the PDF processing pipeline is not closed-loop:

1. After extraction, `graph_views.json` must be generated manually via `export_frontend_artifact.py` + `build_graph_views.py`
2. Weaviate (vector search backend) requires manual Docker startup
3. Switching libraries doesn't reload graph data
4. The frontend has no way to know when graph data is ready after a pipeline completes

The user expects: upload PDF → pipeline runs → graph updates + embeddings stored → see results in UI.

## Goal

1. **Automatic graph rebuilding**: After pipeline finalize, automatically run `export_frontend_artifact` + `build_graph_views` and write the result to the library's workspace so it's immediately visible.
2. **Automatic Weaviate management**: Electron app starts Weaviate Docker container on launch and gracefully handles the case where Docker is unavailable.
3. **Frontend auto-refresh**: When a pipeline job completes, the frontend re-fetches graph data.
4. **Graceful degradation**: If Weaviate is unavailable, embedding steps are skipped with a warning; other pipeline stages still complete.

## Architecture

### Pipeline Changes (Stage 3: finalize)

Current finalize flow:
```
finalize:
  └─ import_manifest(library_id) → embed + upsert to Weaviate
  └─ write result.json
  └─ mark job completed
```

New finalize flow:
```
finalize:
  └─ import_manifest(library_id) → embed + upsert to Weaviate (skip if unavailable)
  └─ export_frontend_artifact(run_dir, library_id) → frontend_artifact.json
  └─ build_graph_views(artifact_path, library_id) → graph_views.json in workspace
  └─ write result.json
  └─ mark job completed
```

### Weaviate Docker Management (Electron)

```
app.on('ready'):
  1. Check if Docker CLI is available (`docker --version`)
  2. Check if weaviate container exists: `docker ps -q -f name=weaviate`
  3. If not running: `docker compose up -d` (using embedded docker-compose.yml)
  4. Health poll: GET http://127.0.0.1:8090/v1/.well-known/ready (30s timeout)
  5. If Docker unavailable or Weaviate fails: set weaviate_available=false, continue
  6. Forward WEAVIATE_URL to backend via env var or --weaviate-url flag
```

A `docker-compose.weaviate.yml` file will be bundled in the app that starts Weaviate with persistent volume at `{data_dir}/weaviate`.

### Frontend Auto-Refresh

In `PipelineView.tsx`, when SSE receives a `completed` event for a job, dispatch a global event that `App.tsx` listens to and re-fetches graph data:

```typescript
// PipelineView.tsx — on job completed
window.dispatchEvent(new CustomEvent('pipeline-completed', { detail: { libraryId } }));

// App.tsx — listener
useEffect(() => {
  const handler = (e: CustomEvent) => {
    api.graph.full(e.detail.libraryId).then(setGraphData);
  };
  window.addEventListener('pipeline-completed', handler);
  return () => window.removeEventListener('pipeline-completed', handler);
}, []);
```

### Map Step Functions

Both scripts need to be importable as functions:

**`export_frontend_artifact.py`**: Add a `run_export(run_dir: Path, library_id: str) -> Path` function that:
1. Reads `raw_llm_outputs.jsonl` from run_dir
2. Builds frontend_artifact.json
3. Writes to `run_dir / "frontend_artifact.json"`
4. Returns the path

**`build_graph_views.py`**: Add a `run_build(artifact_path: Path, library_id: str, workspace_root: Path) -> Path` function that:
1. Reads frontend_artifact.json
2. Builds graph_views.json
3. Writes to `workspace_root / "graph_views.json"`
4. Returns the path

### New API Endpoint

Add `POST /graph/reload?library_id=xxx` to manually trigger graph reload for a specific library, for cases where the pipeline's automatic reload fails.

## Implementation Plan

### Phase 1: Script Encapsulation

1. Refactor `export_frontend_artifact.py` to expose `run_export()` callable function
2. Refactor `build_graph_views.py` to expose `run_build()` callable function
3. Both maintain backward compatibility with CLI usage

### Phase 2: Pipeline Integration

4. Update `_run_finalize()` in `serve_async_pipeline_api.py` to call `run_export()` + `run_build()` after import_manifest
5. Update `pipeline_service.py` to also call graph rebuilding in the finalize step
6. Add `POST /graph/reload` endpoint

### Phase 3: Weaviate Management

7. Create `docker-compose.weaviate.yml` with persistent volume
8. Add Weaviate start/health-check logic to `electron/main.cjs`
9. Add `--weaviate-url` flag to backend or use Settings

### Phase 4: Frontend Auto-Refresh

10. Update `PipelineView.tsx` to dispatch event on job completion
11. Update `App.tsx` to listen for pipeline-completed events
12. Re-fetch graph data with the job's library_id

### Phase 5: Testing

13. End-to-end test: upload PDF → verify graph updates
14. Test Weaviate unavailable scenario (graceful degradation)
15. Test library switch after pipeline completion

## Error Handling

| Step | Error | Behavior |
|------|-------|-----------|
| Weaviate unavailable | Docker not installed or container fails to start | Pipeline continues without embedding; `import_warning` field populated; Weaviate-dependent features (search, RAG) return 503 |
| export_frontend_artifact fails | Extraction output malformed | Log warning, skip graph rebuild, mark job as completed with `graph_warning` field |
| build_graph_views fails | Artifact empty or invalid | Log warning, skip graph rebuild, job still completes |
| Graph reload fails | New graph file invalid | Frontend shows stale graph with warning toast |

## Scope

This design covers the closed-loop pipeline from PDF upload through to visible graph update. It does NOT cover:
- Kafka/database-based job queues (we keep the existing inline/thread model)
- Alternative vector backends (Weaviate only for now)
- PDF parsing alternatives (MineRU only)
- LLM provider configuration (already handled by existing config)