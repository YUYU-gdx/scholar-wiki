# Backend API Interface and Data Model Spec (Implementation-Aligned)

Date: 2026-04-28
Scope: scripts/smj_pipeline/serve_graph_api.py and scripts/smj_pipeline/serve_async_pipeline_api.py
Source of truth: current code behavior

---

## 1. Service Endpoints

1. Graph/Chat/Literature service
- Start: `uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013`
- Base URL: `http://127.0.0.1:8013`

2. Async Pipeline service
- Start: `uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --port 8021`
- Base URL: `http://127.0.0.1:8021`

---

## 2. Graph and Literature APIs (serve_graph_api)

### 2.1 Graph APIs

#### GET /graph/overview
Returns overview subgraph payload:
- `meta`
- `nodes[]`
- `edges[]`
- `moderation_links[]`
- `interaction_links[]`
- `isolated_nodes[]`

#### GET /graph/full
Returns full graph payload:
- `meta`
- `nodes[]`
- `edges[]`
- `moderation_links[]`
- `interaction_links[]`
- `paper_map{}`
- `isolated_nodes[]`

#### GET /graph/search
Query params:
- `query` or `q`
- `mode`: `variable|paper` (default `variable`)
- `limit` or `top_k` (default `20`)
- `keyword_weight` (default `0.5`)
- `vector_weight` (default `0.5`)
- `vector_backend`: `hash|embedding` (current default/use is `hash`)

Response:
- `results[]`
- `search_meta.vector_backend_requested`
- `search_meta.vector_backend_used`
- `search_meta.note`

#### GET /graph/neighborhood
Query params:
- `node_id` (required)
- `hops` (default `1`)
- `limit_nodes` (default `350`)
- `limit_edges` (default `900`)

Errors:
- `404 {"error":"node_not_found","node_id":"..."}`

#### GET /paper/{paper_id_or_doi}
Returns paper detail by `paper_id` or `doi`.

Errors:
- `404 {"error":"paper_not_found","paper_id":"..."}`

#### GET /variable/{var_id}
Returns variable detail and paper aggregation.

Errors:
- `404 {"error":"node_not_found","node_id":"..."}`

### 2.2 Literature APIs

#### POST /literature/import
Request body:
```json
{
  "manifest_path": "path/to/manifest.jsonl",
  "library_id": "supply_chain",
  "options": {}
}
```
Rules:
- `manifest_path` required
- `library_id` required

Errors:
- `400 manifest_path_required|library_id_required`
- `503 literature_service_unavailable`

#### GET /literature/search
Query params:
- `query` or `q` (required)
- `library_id` (required)
- `top_k` or `limit` (default `20`)
- `levels` (default `sentence`)
- `include_expanded_context` (default `true`)
- `keyword_weight` (default `0.4`)
- `rag_weight` (default `0.6`)

Errors:
- `400 query_required|library_id_required`

Degraded response when literature service is unavailable:
```json
{
  "query": "x",
  "library_id": "supply_chain",
  "top_k": 20,
  "levels": ["sentence"],
  "keyword_hits": [],
  "rag_hits": [],
  "merged_hits": [],
  "degraded": true,
  "degraded_reason": "literature_service_unavailable"
}
```

#### POST /literature/answer
Request body:
```json
{
  "query": "question",
  "library_id": "supply_chain",
  "top_k": 5,
  "levels": ["sentence"],
  "keyword_weight": 0.4,
  "rag_weight": 0.6
}
```
Rules:
- `query` required
- `library_id` required

Errors:
- `400 query_required|library_id_required`
- `500 literature_answer_failed`

#### GET /literature/libraries
Response:
```json
{
  "libraries": [
    {
      "library_id": "supply_chain",
      "paper_count": 0,
      "updated_at": "",
      "path": ""
    }
  ],
  "default_library_id": "supply_chain"
}
```

---

## 3. Chat APIs (serve_graph_api)

Important runtime behavior:
- Message submit path is currently forced to agent mode:
  - `mode = "agent"`
  - `provider = "codex"`
  - `model = "codex-local"`

### 3.1 Session APIs

#### POST /chat/sessions
Request body:
```json
{
  "title": "optional",
  "library_id": "supply_chain"
}
```
Rules:
- `library_id` required

Response `201`:
- `session_id`
- `title`
- `default_mode` (currently `agent` at creation path)
- `library_id`

#### GET /chat/sessions?library_id=...
Rules:
- `library_id` required

Response:
```json
{"sessions":[...]}
```

#### GET /chat/sessions/{session_id}?library_id=...
Rules:
- `library_id` required

Errors:
- `404 session_not_found`

#### DELETE /chat/sessions/{session_id}?library_id=...
Deletes (soft-delete semantics handled by chat service).

#### POST /chat/sessions/{session_id}/restore?library_id=...
Restores a deleted session.

Errors:
- `404 session_not_found`
- `409 restore_window_expired`

### 3.2 Message and SSE APIs

#### POST /chat/sessions/{session_id}/messages
Request body:
```json
{
  "content": "user message",
  "stream": true,
  "library_id": "supply_chain"
}
```
Rules:
- `content` required
- `library_id` required

Response `202`:
```json
{
  "session_id": "sess_x",
  "assistant_message_id": "msg_a",
  "user_message_id": "msg_u",
  "stream_url": "/chat/sessions/sess_x/stream?message_id=msg_a"
}
```

Error `500` example:
```json
{
  "error": "chat_submit_failed",
  "detail": "codex_workspace_path_missing:...",
  "error_code": "codex_workspace_path_missing",
  "backend": "codex"
}
```

#### GET /chat/sessions/{session_id}/stream?message_id=...&cursor=0
SSE event stream.

Event types:
- `started`
- `delta`
- `tool_call`
- `citation`
- `agent_item_started`
- `agent_item_delta`
- `agent_item_completed`
- `completed`
- `failed`
- `heartbeat`

---

## 4. Codex Config and Health APIs

#### GET /chat/codex/config
#### POST /chat/codex/config
Load/save global codex runner config.

#### GET /chat/codex/libraries/{library_id}/config
#### POST /chat/codex/libraries/{library_id}/config
Load/save per-library codex config.

Common errors:
- `400 library_id_required`
- `404 codex_workspace_path_missing`

#### POST /chat/codex/libraries/{library_id}/skills/bootstrap
Bootstrap per-library skills template.

#### GET /chat/codex/preflight?library_id=...
Returns structured preflight checks for a library.

#### GET /chat/codex/health
Returns codex availability.
- returns `503` when unavailable (with `reason`)

#### POST /chat/codex/install
Executes configured install command and returns:
- `ok`
- `returncode`
- `stdout` (truncated)
- `stderr` (truncated)

---

## 5. Provider Config APIs

#### GET /chat/provider-config
Returns provider config payload and `config_path`.

#### POST /chat/provider-config
Updates provider config payload.

#### POST /chat/provider-test
Tests provider connectivity.

Request body example:
```json
{
  "provider": "zhipu",
  "model": "glm-4.5-flash",
  "prompt": "Reply with OK only.",
  "options": {"timeout_seconds": 20}
}
```

---

## 6. Workspace Layout APIs

#### GET /api/v2/workspace/layouts
Returns layout list.

#### GET /api/v2/workspace/layout?name=default
Returns one layout by name.

#### POST /api/v2/workspace/layout
Request body:
```json
{
  "name": "default",
  "layout": {}
}
```
Saves layout.

---

## 7. Async Pipeline APIs (serve_async_pipeline_api)

### 7.1 Health APIs

#### GET /healthz
#### GET /v1/pipeline/health

### 7.2 Job Submit APIs

#### POST /v1/pipeline/parse-extract
Content type: `multipart/form-data`

Form fields:
- `file` (PDF, required)
- `library_id` (required)
- `options` (optional JSON string; must be an object if provided)

Success `202` response:
```json
{
  "job_id": "job_xxx",
  "status": "queued",
  "library_id": "supply_chain",
  "workspace_path": "D:/...",
  "file_name": "a.pdf",
  "sse_url": "/v1/jobs/job_xxx/events",
  "result_url": "/v1/jobs/job_xxx/result"
}
```

#### POST /v1/pipeline/parse-extract/batch
Content type: `multipart/form-data`

Form fields:
- `files` (multiple PDFs)
- `library_id` (required)

Response:
- `202` when there are accepted jobs, otherwise `400`
```json
{
  "library_id": "supply_chain",
  "accepted_count": 2,
  "rejected_count": 0,
  "accepted": [],
  "rejected": []
}
```

### 7.3 Job Query APIs

#### GET /v1/jobs
Query params:
- `page` (default `1`)
- `page_size` (default `50`)
- `status`
- `library_id`
- `q`
- `sort` (`created_at_desc|created_at_asc`)

Response:
```json
{
  "jobs": [],
  "total": 0,
  "page": 1,
  "page_size": 50
}
```

#### GET /v1/jobs/{job_id}
Returns one job payload.

Error:
- `404 job_not_found`

#### GET /v1/jobs/{job_id}/result
Returns result only when status is `completed`.

Not ready response:
```json
{"error":"result_not_ready","job_id":"...","status":"queued|running|failed|cancelled"}
```

### 7.4 Job Control APIs

#### POST /v1/jobs/{job_id}/cancel
Allowed states: `queued|running`

Success response:
```json
{
  "job_id": "job_x",
  "status": "cancelled",
  "cancel_requested": true
}
```

Common errors:
- `400 job_not_cancellable`
- `409 job_cancel_race_conflict`

#### POST /v1/jobs/{job_id}/retry
Allowed states: `failed|cancelled`

Success `202` response:
```json
{
  "source_job_id": "job_old",
  "new_job": {
    "job_id": "job_new",
    "status": "queued",
    "library_id": "supply_chain",
    "sse_url": "/v1/jobs/job_new/events",
    "result_url": "/v1/jobs/job_new/result"
  }
}
```

### 7.5 Job Events API

#### GET /v1/jobs/{job_id}/events
SSE event stream.

Event types:
- `accepted`
- `stage_started`
- `stage_progress`
- `stage_done`
- `failed`
- `cancelled`
- `completed`

---

## 8. Core Data Models (API view)

### 8.1 Chat Session Model
```json
{
  "session_id": "sess_x",
  "title": "New Session",
  "default_mode": "agent",
  "library_id": "supply_chain",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### 8.2 Chat Message Model
```json
{
  "message_id": "msg_x",
  "session_id": "sess_x",
  "role": "user|assistant",
  "content": "text",
  "status": "running|completed|failed",
  "citations": [],
  "retrieval": {},
  "tool_trace": [],
  "error_detail": ""
}
```

### 8.3 Pipeline Job Model (public payload)
```json
{
  "job_id": "job_x",
  "display_name": "file.pdf",
  "status": "queued|running|completed|failed|cancelled",
  "status_code": "queued|running|completed|failed|cancelled",
  "stage": "accepted|parse_pdf|extract_entities|finalize",
  "stage_code": "accepted|parse_pdf|extract_entities|finalize",
  "stage_label": "...",
  "progress": 0,
  "library_id": "supply_chain",
  "workspace_path": "D:/...",
  "input_path": "D:/.../input/file.pdf",
  "output_path": "D:/.../result.json",
  "error_code": "",
  "error_detail": "",
  "can_cancel": true,
  "can_retry": false,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### 8.4 Literature Search/Answer Models
```json
{
  "keyword_hits": [],
  "rag_hits": [],
  "merged_hits": [],
  "search_meta": {}
}
```

```json
{
  "answer": "text",
  "citations": [],
  "retrieval": {
    "merged_hits": []
  }
}
```

---

## 9. Common Error Codes (selected)

Common parameter errors:
- `library_id_required`
- `query_required`
- `content_required`
- `session_id_required`
- `message_id_required`

Chat errors:
- `session_not_found`
- `chat_submit_failed` (with `error_code` and `backend`)
- `codex_workspace_path_missing`

Literature errors:
- `literature_service_unavailable`
- `literature_import_failed`
- `literature_search_failed`
- `literature_answer_failed`

Pipeline errors:
- `job_not_found`
- `result_not_ready`
- `job_not_cancellable`
- `job_cancel_race_conflict`
- `job_not_retryable`
- `input_file_missing`
- `library_id_missing`
