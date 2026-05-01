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

## 5. 代码单一事实来源

- 统一约定模块：`scripts/smj_pipeline/runtime_conventions.py`
- Pipeline 落盘：`scripts/smj_pipeline/serve_async_pipeline_api.py`
- 文献物化与 Weaviate 回退：`scripts/smj_pipeline/literature/service.py`
