# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# KN Graph

学术文献知识图谱构建与问答平台，聚焦供应链研究方向。

## 快速启动

```bash
# 新统一入口（FastAPI 单服务，重构中）：
uv run python -m kn_graph serve --port 8013

# 旧版入口（仍在使用）：
# 主 API 服务（图谱 + 对话 + 文献 + 工作区），端口 8013
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013 --views-json outputs/.../graph_views.json --allow-non-supply-chain

# 异步管线 API（PDF 解析 + 抽取任务），端口 8021
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --host 127.0.0.1 --port 8021

# 桌面启动器（同时启动两个服务并打开浏览器）
uv run python scripts/smj_pipeline/app_launcher.py

# 启动 Celery worker（分布式管线执行）
uv run python -m kn_graph worker
```

## 常用命令

```bash
# 运行全部测试（unittest）
uv run python -m unittest discover -s tests -p "test_*.py" -v

# 运行全部测试（pytest）
uv run pytest tests/ -v

# 运行单个测试文件
uv run python -m unittest tests/test_provider_registry.py -v
uv run pytest tests/test_provider_registry.py -v

# 运行单个测试用例
uv run python -m unittest tests.test_provider_registry.TestProviderRegistry.test_load_config -v
uv run pytest tests/test_provider_registry.py::TestProviderRegistry::test_load_config -v
```

## 架构概览

### 当前状态：双服务（正在统一）

1. **serve_graph_api.py** — 基于 stdlib `http.server`，端口 8013。处理图谱视图、对话会话、文献检索、工作区布局及静态前端托管。单文件约 2000 行。
2. **serve_async_pipeline_api.py** — 基于 FastAPI，端口 8021。处理 PDF 上传 → 解析 → 抽取的管线任务生命周期。
3. **kn_mcp_server.py** — stdin/stdout 方式的 MCP 工具服务（非 HTTP）。为 Codex CLI 提供 `rag_search` 和 `graph_search` 工具。

### 目标状态：单一 FastAPI 应用 (`src/kn_graph/`)

重构将两个服务合并到 `src/kn_graph/`，采用基于路由的模块化设计。详见 `docs/superpowers/specs/2026-04-30-backend-unification-design.md`。

```
src/kn_graph/
├── __main__.py          # 入口：python -m kn_graph serve|worker
├── app.py               # FastAPI 应用工厂，挂载所有路由
├── config.py            # Pydantic Settings（环境变量前缀 KN_GRAPH_）
├── routers/             # /graph/*, /chat/*, /literature/*, /pipeline/*, /workspace/*
├── models/              # Pydantic 请求/响应模型
├── services/            # 业务逻辑
├── migration.py         # 旧数据迁移
└── workers/celery_app.py
```

新旧服务的 URL 路径保持一致。

### 抽取管线（核心业务逻辑）

PDF 上传 → MinerU 解析（→ markdown）→ LLM 抽取（→ 结构化 JSON，按 `extraction/schemas.py` 定义）→ 校验 → 可选人工审核 → Postgres 入库 → `build_graph_views.py` → `graph_views.json` 由 API 对外服务。

关键管线脚本位于 `scripts/smj_pipeline/`：
- `extraction/schemas.py` — 抽取结构的 Pydantic 模型（变量、直接效应、交互、调节）
- `extraction/extractor.py` — LLM 抽取执行器
- `extraction/validator.py` — 抽取后校验
- `storage/postgres_repo.py` — Postgres DDL 与 CRUD
- `import_raw_outputs_to_postgres.py` — 批量入库
- `build_graph_views.py` — 从 Postgres 构建 `graph_views.json`

### graph_views.json

API 消费的核心只读数据产物。包含节点（变量/概念）、边（直接效应）、调节链接、交互链接、论文元数据及搜索索引。由 `build_graph_views.py` 从 Postgres 构建。API 通过 `active.json` → 库注册表 → 工作区路径来解析使用哪个 views 文件。

### 文献检索

基于学术论文片段的混合关键词+向量检索。ChromaDB（嵌入式向量数据库）存储嵌入向量，SQLite FTS5 提供 BM25 关键词检索，RRF 融合排序。以文献库为单位隔离存储。

### 对话服务

基于 Codex CLI 的 Agent RAG 对话。会话存储在 SQLite（`chat/store.sqlite`）。对话服务将文献检索、图谱搜索、论文/变量查询及 Codex runner 配置串联在一起。

### scholarai-workbench/

独立的前端应用（Node.js / React + Vite + Tailwind），用于阅读和批注学术论文。基于 Google AI Studio 应用模板构建。**不同于**已废弃的 `frontend/` 目录（该目录禁止修改）。

## 配置

| 环境变量 | 用途 | 默认值 |
|---------------------|---------|---------|
| `KN_GRAPH_PORT` | 主 API 端口 | `8013` |
| `KN_ASYNC_PIPELINE_PORT` | 管线 API 端口 | `8021` |
| `CHAT_STORE_DSN` | 对话存储 DSN | 内存 |
| `PIPELINE_JOB_STORE_DSN` | 管线任务存储 DSN | SQLite |
| `PIPELINE_EXECUTOR` | 执行器类型（`inline` 或 `celery`） | `inline` |
| `PIPELINE_REDIS_URL` | Celery broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | 智谱 API 密钥 | — |
| `NVIDIA_API_KEY` | NVIDIA API 密钥 | — |
| `LLM_PROVIDER_CONFIG_PATH` | LLM 配置文件路径 | `config/llm_providers.json` |
| `CHROMADB_PATH` | ChromaDB 持久化目录 | `{data_dir}/chromadb` |
| `GRAPH_EMBEDDING_MODEL` | 图谱搜索可选嵌入模型 | （哈希回退） |
| `LITERATURE_LIBRARY_INDEX_ROOT` | 文献库索引根目录 | `outputs/literature_libraries` |
| `CHAT_CODEX_CONFIG_PATH` | Codex runner 配置 | `outputs/chat/codex_runner_config.json` |

所有配置项使用 `KN_GRAPH_` 环境变量前缀。本地开发请将 `.env.example` 复制为 `.env`。

## Run 管理

管线输出按 run 组织在 `outputs/runs/` 下。`outputs/runs/active.json` 指向当前活跃的 run。使用 `scripts/smj_pipeline/` 中的脚本管理：
- `list_runs.py` — 列出可用 run
- `activate_run.py` — 切换活跃 run
- `finalize_batch_run.py` — 完成一个批量 run

## 文档索引

- 项目规约总览：`docs/project_spec_index.md`
- 图谱 API 规约：`docs/api.md`
- 异步管线 API 规约：`docs/async_pipeline_api.md`
- 数据模型规约：`docs/data_model.md`
- 文件存储与端口规约：`docs/storage_and_port_conventions.md`
- 后端统一设计：`docs/superpowers/specs/2026-04-30-backend-unification-design.md`

## 重构状态

- **进行中**：后端统一为单一 `src/kn_graph/` FastAPI 包。过渡期间 `scripts/smj_pipeline/` 中的旧脚本仍可正常使用。新代码应放入 `src/kn_graph/`。
- **禁止**：不得创建或修改 `frontend/` 目录的任何内容。

## LLM 提供商配置

- 配置文件：`config/llm_providers.json`
- 对话、异步管线和抽取均使用同一个提供商注册表：`scripts/smj_pipeline/llm/provider_registry.py`
- 覆盖配置路径：`set LLM_PROVIDER_CONFIG_PATH=path/to/config.json`
