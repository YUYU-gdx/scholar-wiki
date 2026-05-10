# Async Pipeline API 规约

## 服务入口
- API：`uv run python -m kn_graph serve --port 8013`
- Pipeline 路由在同一服务内。

## 任务阶段
1. `parse_pdf`（MinerU 精准解析，仅一次，返回 zip 并解包）
2. `materialize_paper`（重命名主 Markdown，落最终目录）
3. `extract_entities`
4. `finalize`

## 接口
- `POST /v1/pipeline/parse-extract`
- `POST /v1/pipeline/parse-extract/batch`
- `GET /v1/jobs`
- `GET /v1/jobs/{id}`
- `GET /v1/jobs/{id}/result`
- `POST /v1/jobs/{id}/cancel`
- `POST /v1/jobs/{id}/retry`
- `GET /v1/jobs/{id}/events`

## 事件流
- `accepted`
- `stage_started`
- `stage_progress`
- `stage_done`
- `failed`
- `cancelled`
- `completed`
