# 项目规约总览（入口）

本文档是 `kn-gragh` 的规约导航，帮助快速定位 API、数据模型、存储、对话服务与提示词约束。

## 1. 核心规约文档
- **API 规约**：`docs/api.md` — 图谱、文献、Chat API、Settings 全部接口
- **数据模型规约**：`docs/data_model.md` — 抽取→存储→产物→API 四层模型 + Chat 数据模型
- **文件存储与端口规约**：`docs/storage_and_port_conventions.md` — 落盘规则、ChromaDB 存储、Chat/Agent 存储
- **Run 管理**：`docs/run_management.md`
- **可复用抽取/评测流程**：`docs/reusable_extract_eval_workflow.md`
- **异步管线 API**：`docs/async_pipeline_api.md`

## 2. 代码事实源（与规约对应）

### 2.1 图谱服务
- API 服务（旧）：`scripts/smj_pipeline/serve_graph_api.py`
- API 服务（新 FastAPI）：`src/kn_graph/app.py`，模块化路由在 `src/kn_graph/routers/`
- 图视图构建：`scripts/smj_pipeline/build_graph_views.py`
- 前端产物导出：`scripts/smj_pipeline/export_frontend_artifact_from_postgres.py`

### 2.2 抽取管线
- 抽取 schema：`scripts/smj_pipeline/extraction/schemas.py`
- 抽取提示词加载：`scripts/smj_pipeline/extraction/prompts.py`
- 抽取执行器：`scripts/smj_pipeline/extraction/extractor.py`
- 抽取校验器：`scripts/smj_pipeline/extraction/validator.py`
- 生产提示词模板：`prompt/extraction_system_prompt.md`

### 2.3 存储层
- PostgreSQL DDL：`scripts/smj_pipeline/storage/schema_postgres.sql`
- PostgreSQL CRUD：`scripts/smj_pipeline/storage/postgres_repo.py`
- 入库脚本：`scripts/smj_pipeline/import_raw_outputs_to_postgres.py`

### 2.4 对话服务 (Chat)
- Chat Service（核心）：`scripts/smj_pipeline/chat_service.py`
- Chat Service（FastAPI 门面）：`src/kn_graph/services/chat_service.py`
- Chat 路由：`src/kn_graph/routers/chat.py`
- Chat 数据模型：`src/kn_graph/models/chat.py`
- Agent Runner 基类 + Codex Runner：`scripts/smj_pipeline/agent_runner.py`
  - `AgentRunner` — 抽象基类
  - `CodexRunner` — 基于 Codex CLI 子进程 + JSON-RPC stdio
  - `ClaudeCodeRunner` — 基于 Claude Agent SDK（`claude-agent-sdk`），进程内运行
  - `HermesRunner` — 占位
  - `AgentRunnerFactory` — 工厂，支持 `codex` / `claude_code` / `hermes`
- Codex 库级配置：`scripts/smj_pipeline/codex_library_config.py`
- MCP 工具服务：`scripts/smj_pipeline/kn_mcp_server.py`

### 2.5 文献检索
- 文献服务：`scripts/smj_pipeline/literature/service.py`
- ChromaDB 客户端：`src/kn_graph/services/literature_service.py`（`ChromaDBClient` 类）

### 2.6 管线 API
- 异步管线 API：`scripts/smj_pipeline/serve_async_pipeline_api.py`
- 任务存储：SQLite / Postgres（通过 `PIPELINE_JOB_STORE_DSN` 切换）

## 3. 统一口径（当前）
- 逻辑抽取模型以 `main_effects` 为主；存储层仍兼容 `direct_effects` 历史表名。
- API 使用 `graph_views.json` 作为服务读取对象；默认来自 `outputs/runs/active.json` 指向的 run。
- 提示词唯一加载源为 `prompt/` 目录。
- Python 执行统一使用 `uv`。
- 对话 Agent 后端可通过 `provider` 参数切换（`codex` / `claude_code`），无需重启服务。
- Claude Code SDK 复用本地 Claude Code 的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` 配置。

## 4. 常用排查路径
1. **接口字段不一致**：先查 `docs/api.md`，再核对 `serve_graph_api.py` / `src/kn_graph/routers/`。
2. **前后端字段不一致**：先查 `docs/data_model.md` 的 L3/L4，再核对 `export_frontend_artifact_from_postgres.py` 与 `build_graph_views.py`。
3. **模型输出解析异常**：查 `prompt/extraction_system_prompt.md` + `extraction/schemas.py`。
4. **入库异常**：查 `schema_postgres.sql` + `import_raw_outputs_to_postgres.py`。
5. **对话 Agent 不可用**：
   - Codex：查 `GET /chat/codex/health` + `/chat/codex/preflight`
   - Claude Code：确认 `ANTHROPIC_API_KEY`（或 `ANTHROPIC_AUTH_TOKEN`）已设置，`claude-agent-sdk` 已安装
6. **SSE 流无响应**：查 `message_id` 是否正确，`cursor` 是否递增，服务端 `event_generator` 循环是否退出。

## 5. 后端统一重构状态
- **进行中**：将 `serve_graph_api.py` + `serve_async_pipeline_api.py` 合并为单一 `src/kn_graph/` FastAPI 应用。
- 过渡期间两个入口均可使用，URL 路径保持兼容。
- 详见 `docs/superpowers/specs/2026-04-30-backend-unification-design.md`。
