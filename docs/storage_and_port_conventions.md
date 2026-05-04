# 文件存储与端口规约（当前实现）

本文档定义 KN Graph 当前后端（`scripts/smj_pipeline`）的用户文件落盘规则与数据库端口回退策略。

## 0. 存储根初始化规约

- 默认存储根：
  - Windows：`D:\KNGraphAppData`
  - 其他系统：`~/.kn_graph_data`
- 也可通过环境变量 `KN_STORAGE_ROOT` 显式指定。
- 任务创建前必须已初始化存储根；未初始化时接口返回 `storage_not_initialized`。
- 初始化接口：
  - `GET /v1/storage/status`
  - `POST /v1/storage/init`（可传 `storage_root`）

## 1. 源文件归档与 Pipeline 任务目录规约

前提：每个任务必须带 `library_id`，并先解析为该库的 `workspace_root`。

源文件先归档（按类型）：

`{workspace_root}/sources/{pdf|markdown|text|html}/{filename}`

然后创建任务目录：

`{workspace_root}/imports/jobs/{job_id}/`

目录与文件约定：

- 上传 PDF：`{job_root}/input/{original_filename}.pdf`
- 解析产物目录：`{job_root}/parse/`
- 解析 Markdown：`{job_root}/parse/parsed.md`
- 解析 HTML：`{job_root}/parse/parsed.html`
- 解析元数据：`{job_root}/parse/parse_meta.json`
- 抽取产物目录：`{job_root}/extract/`
- 抽取原始输出：`{job_root}/extract/raw_llm_outputs.jsonl`
- 人审队列：`{job_root}/extract/review_queue.jsonl`
- 抽取报告：`{job_root}/extract/acceptance_report.md`
- 抽取结果：`{job_root}/extract/extract_result.json`
- 任务总结果：`{job_root}/result.json`

任务分流规则：

- `.pdf`：走 `parse_pdf -> extract_entities -> finalize`
- `.md/.txt/.html/.htm`：走 `prepare_readable -> extract_entities -> finalize`
- 其他后缀：拒绝（`unsupported_source_type`）

## 2. 导入后语料物化规约（含 MD 阅读目录）

当文献导入执行 `import_manifest` 后，按 `paper_key` 写入工作区：

`{workspace_root}/corpus/papers/{paper_key}/`

约定：

- 原始 PDF：`source/{safe_name}.pdf`
- 规范 HTML：`derived/html/article.html`
- MinerU 输出目录：`derived/mineru/latest/`
- 论文元数据：`meta/paper.json`
- 工作区索引：`{workspace_root}/corpus/index/papers.ndjson`
- 阅读用 MD 目录：`{workspace_root}/corpus/md_library/{paper_key}/`
  - 复制解析产物整包（包含图片等资源）
  - `md_library_path` 指向该源文件对应的主 Markdown 文件

## 3. 任务状态库规约

- 默认存储类型：SQLite
- 默认 SQLite 路径：`outputs/workbench/pipeline_jobs.sqlite`
- 若设置 `PIPELINE_JOB_STORE_DSN`：改用 Postgres

## 4. Weaviate 端口回退规约

用于文献检索/向量存储连接：

1. 若设置 `WEAVIATE_URL`，只使用该地址。
2. 否则依次探测：
   - `http://127.0.0.1:8080`
   - `http://127.0.0.1:8090`
3. 若都不可达，仍回退到第一个候选地址：`http://127.0.0.1:8080`。

## 6. Chat / Agent 存储规约

### 6.1 Chat 会话存储
- 默认存储类型：SQLite（内存回退）
- 默认 SQLite 路径：`outputs/chat/store.sqlite`
- 若设置 `CHAT_STORE_DSN`：改用 Postgres

### 6.2 Agent 配置文件位置
- 全局 Codex Runner 配置：`{data_dir}/chat/codex_runner_config.json`
  - 可通过 `CHAT_CODEX_CONFIG_PATH` 覆盖
- 库级 Codex 配置：`{workspace}/.codex/library_codex_config.json`
  - 含 `codex_home`、`mcp_servers`、`project_skills`
- Agent 选择设置：`{data_dir}/chat/agent_settings.json`
  - 含 `current_agent` 字段
- 各 Agent 独立配置：`{data_dir}/chat/{agent_id}_config.json`
  - 如 `{data_dir}/chat/claude_code_config.json`
  - 如 `{data_dir}/chat/codex_config.json`
- 翻译提供商配置：`{data_dir}/chat/translation_provider_config.json`

### 6.3 Claude Code (Agent SDK) 环境变量
- `ANTHROPIC_API_KEY` — API 密钥（SDK 必需；若未设置则自动从 `ANTHROPIC_AUTH_TOKEN` 桥接）
- `ANTHROPIC_BASE_URL` — 自定义 API 端点（如 `https://api.deepseek.com/anthropic`）
- `ANTHROPIC_MODEL` — 模型标识（如 `DeepSeek-V4-pro[1M]`）
- Agent SDK 启动时无额外子进程，直接在当前 Python 进程中运行 agent 循环

### 6.4 Codex CLI 存储
- Codex 会话/线程状态存储在 `CODEX_HOME` 指向的目录
- 库级隔离时通过 `CHAT_CODEX_HOME` 或 `CHAT_CODEX_FORCE_LIBRARY_HOME=1` 指定
- MCP 配置由 Codex Runner 在运行时生成至 `{workspace}/.codex/mcp_servers.json`
- kn_graph MCP 工具（`rag_search`、`graph_search`、`weaviate_query`、`weaviate_fetch_object`）通过 `scripts/smj_pipeline/kn_mcp_server.py` 提供

## 7. 代码单一事实来源

- 统一约定模块：`scripts/smj_pipeline/runtime_conventions.py`
- Pipeline 落盘：`scripts/smj_pipeline/serve_async_pipeline_api.py`
- 文献物化与 Weaviate 回退：`scripts/smj_pipeline/literature/service.py`
