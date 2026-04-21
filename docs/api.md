# 图谱 API 规约

## 1. 基础信息
- 服务脚本：`scripts/smj_pipeline/serve_graph_api.py`
- 默认地址：`http://127.0.0.1:8013`
- 默认前端目录：`outputs/smj_batch_full/frontend`
- 默认数据来源：`outputs/runs/active.json` 指向的 `graph_views.json`
- 默认数据范围限制：仅允许 `outputs/smj_supply_chain_batch` 下的 `graph_views.json`，如需放开必须显式传 `--allow-non-supply-chain`

## 2. 启动与数据选择
- 使用活动 run：
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013
```
- 显式指定视图文件：
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --views-json outputs/runs/<run_id>/graph_views.json --port 8013
```

## 3. 通用约定
- 所有接口返回 `application/json; charset=utf-8`（静态资源除外）。
- 查询参数解析规则：
  - 字符串参数为空时按默认值处理。
  - 数值参数非法会触发 Python 转换异常（当前无统一错误包装）。
- 404 场景：
  - `/paper/{id}` 找不到返回 `{"error":"paper_not_found","paper_id":"..."}`。
  - `/variable/{id}` 或 `/graph/neighborhood?node_id=...` 找不到返回 `{"error":"node_not_found","node_id":"..."}`。

## 4. API 列表

### 4.1 `GET /graph/full`
- 用途：返回全量图数据。
- 响应：
  - `meta`
  - `nodes[]`
  - `edges[]`
  - `moderation_links[]`
  - `interaction_links[]`

### 4.2 `GET /graph/overview`
- 用途：返回预计算概览子图（用于首屏提速）。
- 响应：
  - `meta`
  - `nodes[]`（`overview.node_ids` 对应节点）
  - `edges[]`（`overview.edge_indexes` 对应边）
  - `moderation_links[]`
  - `interaction_links[]`

### 4.3 `GET /graph/neighborhood`
- 用途：返回某节点的局部邻域。
- 参数：
  - `node_id` 必填
  - `hops` 默认 `1`
  - `limit_nodes` 默认 `350`
  - `limit_edges` 默认 `900`
- 响应：
  - `node_id`
  - `nodes[]`
  - `edges[]`
  - `moderation_links[]`（与邻域节点相关）
  - `interaction_links[]`（与邻域节点相关）

### 4.4 `GET /graph/search`
- 用途：变量/论文检索（关键词 + 本地哈希向量混合评分）。
- 参数：
  - `mode=variable|paper`，默认 `variable`
  - `query` 或 `q`
  - `limit` 或 `top_k`，默认 `20`
  - `keyword_weight`，默认 `0.5`
  - `vector_weight`，默认 `0.5`
  - `vector_backend`，可传 `hash|embedding`，当前实际使用 `hash`
- 响应：
  - `results[]`
  - `search_meta`
    - `vector_backend_requested`
    - `vector_backend_used`
    - `note`（当请求 embedding 但未配置时给出 fallback 说明）

### 4.5 `GET /paper/{paper_id_or_doi}`
- 用途：返回单篇论文详情。
- 匹配顺序：先按 `paper_map` key，失败后再遍历 `paper_id` / `doi`。
- 响应核心字段：
  - 元数据：`paper_id`、`doi`、`publication_date`、`online_date`、`publication_year`、`paper_citation_count`
  - 访问路径：`offline_html_path`、`article_url`
  - 分流信息：`extractability_status`、`paper_type`、`extractability_reason`、`extractability_evidence_section`
  - 结构化内容：`paper_domains[]`、`context_variables[]`、`operationalization{}`、`variable_definitions[]`、`main_effects[]`、`moderations[]`、`interactions[]`

### 4.6 `GET /variable/{var_id}`
- 用途：返回变量节点详情及论文聚合视图。
- 响应核心字段：
  - `node`
  - `paper_count_total`
  - `paper_count_edge`
  - `paper_count_moderation`
  - `paper_count_interaction`
  - `papers[]`（兼容结构，含 `mentions`）
  - `paper_groups[]`（前端主用结构）
    - `paper_id`、`doi`、`publication_year`
    - `open_local_html`、`open_online_url`
    - `concepts[]`（来自 `variable_definitions`）
    - `measurement_methods[]`（来自 `operationalization`）
    - `relations[]`（`direct_effect` / `moderation` / `interaction` 摘要）

### 4.7 `POST /literature/import`
- 用途：导入文献清单并完成标准化/切分/embedding/索引。
- 请求体：
  - `manifest_path`：JSONL 清单路径（必填）
  - `library_id`：文献库标识（可选，建议传；也可放在 `options.library_id`）
  - `options`：预留扩展参数（可选）
- 响应核心字段：
  - `library_id`
  - `imported_count`
  - `sentence_count`
  - `paragraph_count`
  - `document_count`

最小调用示例（单篇 MD）：
```json
{
  "manifest_path": "outputs/literature_base/manifest_one.jsonl"
}
```

`manifest_one.jsonl` 样例（单行 JSON）：
```json
{"paper_id":"0ecc6383-a6cb-407f-bc57-a9d0f99a19bc","doi":"md::0ecc6383-a6cb-407f-bc57-a9d0f99a19bc","title":"0ecc6383-a6cb-407f-bc57-a9d0f99a19bc","source_path":"outputs/mineru_recovery_full_from_outputs_20260419_120258/downloads/final_named/0ecc6383-a6cb-407f-bc57-a9d0f99a19bc.md"}
```

成功响应示例：
```json
{
  "manifest_path": "outputs/literature_base/manifest_one.jsonl",
  "imported_count": 1,
  "sentence_count": 120,
  "paragraph_count": 18,
  "document_count": 1
}
```

运行依赖环境变量：
- `WEAVIATE_URL`（例如 `http://127.0.0.1:8090`）
- `ZHIPU_API_KEY`
- 可选：`LITERATURE_EMBEDDING_MODEL`（默认 `embedding-3`）

### 4.8 `GET /literature/search`
- 用途：双路召回（关键词 BM25 + 向量 RAG）并做加权 RRF 融合。
- 参数：
  - `query`（必填）
  - `library_id`（可选；传入后仅在该库内召回，不传则跨库）
  - `top_k` 默认 `20`
  - `levels`：`sentence|paragraph|document`，可逗号拼接，默认 `sentence`
  - `keyword_weight` 默认 `0.4`
  - `rag_weight` 默认 `0.6`
  - `include_expanded_context` 默认 `true`
- 响应核心字段：
  - `keyword_hits[]`
  - `rag_hits[]`
  - `merged_hits[]`
  - `search_meta`
    - `library_filter_applied`：是否成功应用库过滤
    - `library_filter_mode`：`weaviate_where`（原生过滤）或 `paper_id_registry`（应用层库索引过滤）
    - `library_registry_paper_count`：应用层库索引中的论文数（仅 fallback 模式有意义）

### 4.9 `POST /literature/answer`
- 用途：在召回结果上生成回答（GLM chat）。
- 请求体：
  - `query`（必填）
  - `library_id`（可选；传入后仅在该库内召回）
  - `top_k` 默认 `5`
  - `levels` 默认 `["sentence"]`
  - `keyword_weight` 默认 `0.4`
  - `rag_weight` 默认 `0.6`
- 响应核心字段：
  - `answer`
  - `citations[]`
  - `retrieval`（包含召回明细）

## 5. 静态资源接口
- `GET /`
- `GET /frontend/`
- `GET /frontend/<asset>`

## 6. 环境变量（与接口行为相关）
- `GRAPH_EMBEDDING_MODEL`
  - 仅用于声明 embedding 检索意图。
  - 当前实现仍回退到哈希向量，不会真正调用外部 embedding 服务。

## 7. Chat API（新增）

### 7.1 `POST /chat/sessions`
- 用途：创建会话。
- 请求体：
  - `title`（可选）
  - `default_mode`：`fast|agent`（可选，默认 `fast`）
- 响应：`{session_id, title, default_mode, created_at, updated_at}`

### 7.2 `GET /chat/sessions`
- 用途：获取会话列表（按更新时间倒序）。
- 响应：`{sessions:[...]}`

### 7.3 `GET /chat/sessions/{session_id}`
- 用途：获取会话详情与历史消息。
- 响应：
  - `session`
  - `messages[]`（含 `role`、`content`、`status`、`citations`、`retrieval`、`tool_trace`）

### 7.4 `POST /chat/sessions/{session_id}/messages`
- 用途：提交消息并触发回答。
- 请求体：
  - `content`（必填）
  - `mode`: `fast|agent`
  - `provider`: `glm|zhipu|deepseek`
  - `model`（可选）
  - `stream`（可选，默认 `true`）
- 响应：`202`
  - `assistant_message_id`
  - `user_message_id`
  - `stream_url`

### 7.5 `GET /chat/sessions/{session_id}/stream?message_id=...`
- 用途：SSE 事件流。
- 事件类型：
  - `started`
  - `delta`
  - `tool_call`
  - `citation`
  - `completed`
  - `failed`
