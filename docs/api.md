# 图谱 API 规约

## 1. 基本信息
- 服务入口：`scripts/smj_pipeline/serve_graph_api.py`（旧） / `python -m kn_graph serve`（新 FastAPI）
- 默认地址：`http://127.0.0.1:8013`
- 默认数据来源：`outputs/runs/active.json` 指向的 `graph_views.json`
- 默认数据范围：供应链（`supply_chain`），可通过 `--allow-non-supply-chain` 放开限制

## 2. 启动方式与命令行选项
- 使用活动 run：
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013
```
- 显式指定视图文件：
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --views-json outputs/runs/<run_id>/graph_views.json --port 8013
```
- 新 FastAPI 统一入口：
```powershell
uv run python -m kn_graph serve --port 8013
```

## 3. 通用约定
- 所有接口返回 `application/json; charset=utf-8`（静态资源除外）。
- 查询参数校验宽松：
  - 字符串为空时沿用默认值。
  - 数值越界时前端统一捕获并包装。
- 404 响应：
  - `/paper/{id}` 找不到返回 `{"error":"paper_not_found","paper_id":"..."}`。
  - `/variable/{id}` 与 `/graph/neighborhood?node_id=...` 找不到返回 `{"error":"node_not_found","node_id":"..."}`。

## 4. 图谱 API

### 4.1 `GET /graph/full`
- 用途：返回完整图数据。
- 响应：
  - `meta`
  - `nodes[]`
  - `edges[]`
  - `moderation_links[]`
  - `interaction_links[]`

### 4.2 `GET /graph/overview`
- 用途：返回预计算概览图（大图降采样）。
- 响应：
  - `meta`
  - `nodes[]`（对应 `overview.node_ids`）
  - `edges[]`（对应 `overview.edge_indexes`）
  - `moderation_links[]`
  - `interaction_links[]`

### 4.3 `GET /graph/neighborhood`
- 用途：返回某节点的局部邻域。
- 参数：
  - `node_id`（必填）
  - `hops`（默认 `1`）
  - `limit_nodes`（默认 `350`）
  - `limit_edges`（默认 `900`）
- 响应：
  - `node_id`
  - `nodes[]`
  - `edges[]`
  - `moderation_links[]`（与该节点相关）
  - `interaction_links[]`（与该节点相关）

### 4.4 `GET /graph/search`
- 用途：关键词 + 向量哈希搜索（变量/论文）。
- 参数：
  - `mode=variable|paper`（默认 `variable`）
  - `query` 或 `q`
  - `limit` 或 `top_k`（默认 `20`）
  - `keyword_weight`（默认 `0.5`）
  - `vector_weight`（默认 `0.5`）
  - `vector_backend`：可选 `hash|embedding`，当前实现使用 `hash`
- 响应：
  - `results[]`
  - `search_meta`
    - `vector_backend_requested`
    - `vector_backend_used`
    - `note`（当 embedding 未配置时的 fallback 说明）

## 5. 论文/文献 API

### 5.1 `GET /paper/{paper_id_or_doi}`
- 用途：返回单篇论文详情。
- 匹配顺序：先按 `paper_map` key，失败后遍历 `paper_id` / `doi`。
- 响应主要字段：
  - 元数据：`paper_id`、`doi`、`publication_date`、`online_date`、`publication_year`、`paper_citation_count`
  - 文件路径：`source_pdf_path`、`source_md_path`、`offline_html_path`、`article_url`
  - 提取信息：`extractability_status`、`paper_type`、`extractability_reason`、`extractability_evidence_section`
  - 结构化数据：`paper_domains[]`、`context_variables[]`、`operationalization{}`、`variable_definitions[]`、`main_effects[]`、`moderations[]`、`interactions[]`

### 5.2 `GET /paper/{paper_id_or_doi}/files`
- 用途：返回论文对应的可读文件列表（PDF / Markdown / HTML）。
- 参数：`library_id`（可选）
- 响应示例：
  ```json
  {
    "paper_id": "doi_smith2023",
    "library_id": "supply_chain",
    "files": {
      "pdf": { "path": "D:\\data\\...\\source\\smith2023.pdf", "name": "smith2023.pdf", "size_bytes": 2345678 },
      "markdown": { "path": "D:\\data\\...\\mineru\\latest\\full.md", "name": "full.md", "size_bytes": 45678 }
    },
    "default_view": "pdf"
  }
  ```
- 可用文件优先级：PDF > Markdown > HTML。`default_view` 为 `"none"` 时表示无可读文件。
- Markdown 检测逻辑：若 `source_md_path` 为文件则直接返回；若为目录则查找 `full.md`、`merged.md`、`output.md`。

### 5.3 `GET /variable/{var_id}`
- 用途：返回变量节点详情及论文聚合视图。
- 响应主要字段：
  - `node`
  - `paper_count_total`、`paper_count_edge`、`paper_count_moderation`、`paper_count_interaction`
  - `papers[]`（含 `mentions` 数据结构）
  - `paper_groups[]`（当前使用结构）：
    - `paper_id`、`doi`、`publication_year`
    - `open_local_html`、`open_online_url`
    - `concepts[]`（来自 `variable_definitions`）
    - `measurement_methods[]`（来自 `operationalization`）
    - `relations[]`（`direct_effect` / `moderation` / `interaction` 摘要）

## 6. 文献库 API

### 6.1 `POST /literature/import`
- 用途：导入文献清单，完成标准化/切分/embedding/入库。
- 请求体：
  - `manifest_path`（JSONL 清单路径，必填）
  - `library_id`（文献库标识，可选，也可放在 `options.library_id` 中）
  - `options`（预留扩展，可选）
- 响应主要字段：
  - `library_id`、`imported_count`、`sentence_count`、`paragraph_count`、`document_count`

最小示例（单篇 MD）：
```json
{
  "manifest_path": "outputs/literature_base/manifest_one.jsonl"
}
```
`manifest_one.jsonl` 每行为一个 JSON：
```json
{"paper_id":"0ecc6383-...","doi":"md::0ecc6383-...","title":"...","source_path":"outputs/mineru_recovery_full_from_outputs_20260419_120258/downloads/final_named/0ecc6383-....md"}
```
- 依赖环境变量：`WEAVIATE_URL`（默认 `http://127.0.0.1:8090`）、`ZHIPU_API_KEY`
- 可选：`LITERATURE_EMBEDDING_MODEL`（默认 `embedding-3`）

### 6.2 `GET /literature/search`
- 用途：双路召回——关键词 BM25 + 向量 RAG，加权 RRF 融合。
- 参数：
  - `query`（必填）
  - `library_id`（可选，限定在该库内召回）
  - `top_k`（默认 `20`）
  - `levels`：`sentence|paragraph|document`，可多值拼接（默认 `sentence`）
  - `keyword_weight`（默认 `0.4`）
  - `rag_weight`（默认 `0.6`）
  - `include_expanded_context`（默认 `true`）
- 响应主要字段：
  - `keyword_hits[]`、`rag_hits[]`、`merged_hits[]`
  - `search_meta`：
    - `library_filter_applied`
    - `library_filter_mode`（`weaviate_where` / `paper_id_registry`）
    - `library_registry_paper_count`

### 6.3 `POST /literature/answer`
- 用途：基于召回结果生成回答（GLM chat）。
- 请求体：
  - `query`（必填）
  - `library_id`（可选）
  - `top_k`（默认 `5`）
  - `levels`（默认 `["sentence"]`）
  - `keyword_weight`（默认 `0.4`）
  - `rag_weight`（默认 `0.6`）
- 响应主要字段：`answer`、`citations[]`、`retrieval`（含召回详情）

## 7. Chat API（对话服务）

Chat API 提供多 Agent 后端的对话能力，支持 SSE 流式返回。Agent 后端可通过 `provider` 字段切换。

### 7.1 会话管理

#### `GET /chat/sessions`
- 用途：获取会话列表（按更新时间倒序）。
- 参数：`library_id`（可选）
- 响应：`{"sessions": [{session_id, title, default_mode, library_id, created_at, updated_at, deleted_at, source}, ...]}`
- `source` 字段标识后端：`"codex"` / `"claude_code"`

#### `GET /chat/sessions/{session_id}`
- 用途：获取会话详情及历史消息。
- 参数：`library_id`（可选）
- 响应：
  ```json
  {
    "session": {"session_id": "...", "title": "...", "source": "claude_code", ...},
    "messages": [
      {
        "message_id": "...", "session_id": "...", "role": "user|assistant",
        "mode": "agent|fast", "provider": "claude_code", "model": "...",
        "content": "...",
        "citations": [...], "retrieval": {...}, "tool_trace": [...],
        "status": "completed|running|failed",
        "error_code": "...", "error_backend": "..."
      }
    ]
  }
  ```

#### `POST /chat/sessions`
- 用途：创建新会话。
- 请求体：
  ```json
  {
    "title": "会话标题",
    "library_id": "供应链"
  }
  ```
- 响应：`201` + `{"session_id": "...", "title": "...", "default_mode": "agent", "source": "claude_code", ...}`

#### `DELETE /chat/sessions/{session_id}`
- 用途：软删除会话（5 分钟内可恢复）。
- 参数：`library_id`（可选）
- 响应：
  ```json
  {
    "session_id": "...",
    "deleted_at": "2026-05-04T...",
    "undo_window_seconds": 5,
    "undo_deadline": "2026-05-04T...",
    "source": "claude_code"
  }
  ```

#### `POST /chat/sessions/{session_id}/restore`
- 用途：恢复软删除的会话（需在过期窗口内）。
- 参数：`library_id`（可选）
- 响应：`{"session_id": "...", "restored": true, "source": "claude_code"}`
- 错误：`409`（窗口过期） / `404`（会话不存在）

### 7.2 消息发送与流式传输

#### `POST /chat/sessions/{session_id}/messages`
- 用途：提交消息并触发异步回答。
- 请求体：
  ```json
  {
    "content": "供应链韧性有哪些关键影响因素？",
    "mode": "agent",
    "provider": "claude_code",
    "model": "",
    "stream": true,
    "library_id": "供应链"
  }
  ```
  | 字段 | 说明 |
  |------|------|
  | `content` | 消息内容（必填） |
  | `mode` | `"agent"`（Agent 工具调用模式）或 `"fast"`（直接 LLM 回答） |
  | `provider` | Agent 后端标识：`"codex"` / `"claude_code"` / `"hermes"` |
  | `model` | 预留，由前端 Agent 设置页决定 |
  | `stream` | 是否流式返回（默认 `true`） |
  | `library_id` | 文献库标识（agent 模式必填） |

- 响应：`202`
  ```json
  {
    "session_id": "...",
    "assistant_message_id": "msg_abc123",
    "user_message_id": "msg_xyz789",
    "stream_url": "/chat/sessions/{session_id}/stream?message_id=msg_abc123"
  }
  ```

#### `GET /chat/sessions/{session_id}/stream`
- 用途：SSE 事件流，前端轮询获取消息处理进度。
- 参数：
  - `message_id`（必填）
  - `cursor`（默认 `0`，游标递增）
- 事件类型：

| 事件 | 说明 | 负载字段 |
|------|------|----------|
| `started` | 消息处理开始 | `message_id`, `mode` |
| `status` | 阶段状态 | `stage`（retrieve/generate/done）, `label`, `state` |
| `tool_call` | 工具调用事件 | `backend`, `step_id`, `state`（started/completed/failed）, `tool`, `kind`（tool/command/file_change/system）, `summary`, `args_preview`, `output_summary`, `detail`, `raw` |
| `agent_item_started` | Agent 子任务开始 | `backend`, `step_id`, `item`, `kind`, `summary` |
| `agent_item_delta` | Agent 子任务流式增量 | `backend`, `step_id`, `kind`, `text`, `summary` |
| `agent_item_completed` | Agent 子任务完成 | `backend`, `step_id`, `item`, `kind`, `summary` |
| `delta` | 回答文本流式增量 | `text` |
| `citation` | 引用/证据 | `phase`, `reason`（降级时） |
| `completed` | 回答完成 | `message_id`, `answer`, `citations`, `tool_trace`, `retrieval_trace` |
| `failed` | 回答失败 | `message_id`, `error`, `error_code`, `backend`, `library_id` |
| `heartbeat` | 心跳保持连接 | 空 `{}` |

- `tool_trace` 条目格式：
  ```json
  {
    "backend": "claude_code",
    "step": 1, "step_id": "call_00_abc123",
    "state": "completed", "kind": "tool",
    "tool": "Bash", "summary": "Bash",
    "args": {"command": "ls", "description": "List files"},
    "args_preview": "{\"command\":\"ls\"...}",
    "output_summary": "...",
    "detail": "{...}",
    "raw": {"arguments": {...}, "result": {...}}
  }
  ```

### 7.3 Agent 后端管理

#### `GET /chat/codex/health`
- 用途：Codex CLI 健康检查。
- 响应：`{"backend": "codex", "available": true|false, "reason": "...", "version": "..."}`

#### `GET /chat/codex/config`
- 用途：获取 Codex Runner 全局配置。
- 响应：`{"config": {app_server_command, app_server_args, model, approval_policy, sandbox_mode, mcp_servers, ...}}`

#### `POST /chat/codex/config`
- 用途：保存 Codex Runner 全局配置。
- 请求体：同 config 结构（部分更新）。

#### `POST /chat/codex/install`
- 用途：安装 Codex CLI（`npm install -g @openai/codex`）。

#### `GET /chat/codex/preflight`
- 用途：Codex 环境全面预检。
- 参数：`library_id`（必填）
- 响应：
  ```json
  {
    "ok": true, "severity": "ok|warn|error",
    "library_id": "...", "summary": "...",
    "checks": [
      {"check_id": "...", "name": "codex_health", "passed": true, "severity": "ok", ...},
      {"check_id": "...", "name": "workspace_path", "passed": true, "severity": "ok", ...},
      {"check_id": "...", "name": "library_codex_config", "passed": true, "severity": "ok", ...},
      {"check_id": "...", "name": "mcp_rag_search_probe", "passed": true, "severity": "ok", ...}
    ],
    "failed_count": 0, "warning_count": 0, "error_count": 0
  }
  ```

#### `GET /chat/codex/libraries/{library_id}/config`
- 用途：获取指定文献库的 Codex 配置（含 MCP servers、project skills、codex_home）。
- 响应：`{"config": {codex_home, mcp_servers, project_skills, workspace_path, ...}}`

#### `POST /chat/codex/libraries/{library_id}/config`
- 用途：保存指定文献库的 Codex 配置。

#### `POST /chat/codex/libraries/{library_id}/skills/bootstrap`
- 用途：引导（bootstrap）指定文献库的项目级 skills。

### 7.4 LLM 提供商配置

#### `GET /chat/provider-config`
- 用途：获取 LLM 提供商注册表配置。
- 响应：
  ```json
  {
    "default_provider": "zhipu",
    "providers": [
      {"id": "zhipu", "default_model": "glm-4.5-flash", "api_key_env": "ZHIPU_API_KEY", "base_url": "...", "models": [...]},
      ...
    ],
    "config_path": "config/llm_providers.json"
  }
  ```

#### `POST /chat/provider-config`
- 用途：更新 LLM 提供商配置。

#### `POST /chat/provider-test`
- 用途：测试 LLM 提供商连接。
- 请求体：
  ```json
  {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "options": {"api_key": "...", "base_url": "..."},
    "prompt": "Reply with OK only."
  }
  ```
- 响应：`{"ok": true, "provider": "deepseek", "model": "deepseek-v4-flash", "response_preview": "OK"}`

### 7.5 翻译服务

#### `GET /chat/translation-provider-config`
- 用途：获取翻译提供商配置。
- 响应：`{"active_provider": "deepseek", "provider": "deepseek", "model": "deepseek-v4-pro", "target_lang": "zh", ...}`

#### `POST /chat/translation-provider-config`
- 用途：保存翻译提供商配置。

#### `POST /chat/translate`
- 用途：执行文本翻译。
- 请求体：
  ```json
  {
    "text": "Supply chain resilience is critical.",
    "target_lang": "zh",
    "provider": "deepseek",
    "model": "deepseek-v4-pro",
    "api_key": "sk-...",
    "base_url": "https://api.deepseek.com"
  }
  ```
- 响应：`{"translated_text": "供应链韧性至关重要。", "provider": "deepseek", "model": "deepseek-v4-pro", "target_lang": "zh", "latency_ms": 1234}`

## 8. 全局设置

### `GET /settings`
- 用途：获取所有前端可配置的设定（Pipeline / 翻译 / Agent）。
- 响应：
  ```json
  {
    "schema": {
      "version": 2,
      "categories": [
        {"id": "pipeline", "title": "Pipeline", "restart_required": false},
        {"id": "translation", "title": "翻译", "restart_required": false},
        {"id": "agent_settings", "title": "Agent 设置", "restart_required": true}
      ]
    },
    "settings": {
      "pipeline": {...},
      "translation": {...},
      "agent_settings": {...}
    },
    "updated_at": "2026-05-04T..."
  }
  ```

### `PUT /settings/agent_settings`
- 用途：更新 Agent 设置（含后端切换、提供商配置）。
- 请求体：
  ```json
  {
    "current_agent": "claude_code",
    "provider": "anthropic",
    "model": "claude-sonnet-4-6",
    "api_key": "sk-...",
    "base_url": "https://api.deepseek.com/anthropic",
    "endpoint_url": ""
  }
  ```
- 重要：`current_agent` 切换后需页面刷新以重建 SSE 连接；切换前已有的会话仍可正常读取历史消息。
- `available_agents`：`["claude_code", "codex", "gemini_cli", "hermes", "openclaw", "opencode"]`

## 9. 静态资源
- `GET /` — 前端 SPA 入口
- `GET /assets/*` — 前端静态资源

## 10. 环境变量参考（图谱/检索相关）
- `GRAPH_EMBEDDING_MODEL` — 若设置则使用远程 embedding 做图搜索；当前实现以哈希回退为主
- `WEAVIATE_URL` — 向量数据库地址（默认 `http://127.0.0.1:8090`）
- `LITERATURE_LIBRARY_INDEX_ROOT` — 文献库索引根目录（默认 `outputs/literature_libraries`）
