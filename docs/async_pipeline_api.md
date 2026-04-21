# Async Pipeline API（PDF 解析 + 实体提取）

## 1. 目标

提供端到端异步任务接口，前端上传 PDF 后立即返回 `job_id`，后端异步执行：

1. `parse_pdf`
2. `extract_entities`
3. `finalize`

支持 `SSE` 事件流、任务状态查询、任务取消。

## 2. 启动方式

### 2.1 启动 API

```powershell
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --host 127.0.0.1 --port 8021
```

### 2.2 启动 Celery Worker

```powershell
uv run celery -A scripts.smj_pipeline.serve_async_pipeline_api:celery_app worker -l info
```

如果只想本地调试（不启 worker），可使用 inline 执行器：

```powershell
set PIPELINE_EXECUTOR=inline
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py
```

## 3. 环境变量

- `PIPELINE_EXECUTOR`：`celery|inline`（默认 `celery`）
- `PIPELINE_REDIS_URL`：Redis 地址（默认 `redis://127.0.0.1:6379/0`）
- `PIPELINE_CELERY_BACKEND`：Celery 结果后端（默认同 Redis）
- `PIPELINE_TASK_ALWAYS_EAGER`：`1/true` 时 Celery eager 模式（测试用）
- `PIPELINE_JOB_STORE_DSN`：PostgreSQL DSN；设置后使用 Postgres 持久化 `pipeline_jobs`
- `ZHIPU_API_KEY` / `NVIDIA_API_KEY`：抽取阶段 LLM key

## 4. API 列表

### 4.1 `POST /v1/pipeline/parse-extract`

- 请求：`multipart/form-data`
  - `file`：PDF 文件（必填）
  - `options`：JSON 字符串（可选）
- 响应：`202`

```json
{
  "job_id": "job_xxx",
  "status": "queued",
  "sse_url": "/v1/jobs/job_xxx/events",
  "result_url": "/v1/jobs/job_xxx/result"
}
```

### 4.2 `GET /v1/jobs/{job_id}`

返回任务状态快照（当前阶段、进度、错误、输入输出路径等）。

### 4.3 `GET /v1/jobs/{job_id}/result`

- 任务完成时返回 `200 + result`
- 未完成返回 `404 result_not_ready`

### 4.4 `POST /v1/jobs/{job_id}/cancel`

设置软取消标记；任务在阶段检查点感知后转 `cancelled`。

### 4.5 `GET /v1/jobs/{job_id}/events`

`SSE` 事件流，事件类型：

- `accepted`
- `stage_started`
- `stage_progress`
- `stage_done`
- `failed`
- `cancelled`
- `completed`

## 5. 产物目录

每个任务在 `outputs/runs/<job_id>/` 下产生：

- `input/`：上传原始 PDF
- `parse/`：`parsed.md`、`parsed.html`、`parse_meta.json`
- `extract/`：抽取中间结果与报告
- `result.json`：最终汇总结果

