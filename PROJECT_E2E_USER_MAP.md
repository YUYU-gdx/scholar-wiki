# 项目端到端功能与用户地图总览

> 文档定位：本文件整理当前仓库所有可用的端到端能力、关键接口与用户旅程（User Map），用于产品对齐、联调、测试与运维。
> 
> 事实来源：代码与测试（`tests/test_*.py`）+ 现有文档（`README.md`、`docs/api.md`、`docs/chat_test_routes.md`）。

## 1. 系统全景

当前项目可视为 3 条主线能力：

1. 图谱与问答前端线（Graph + Chat）
- 图谱入口：`/frontend/`
- Chat 入口：`/frontend/chat/`
- 核心后端：`scripts/smj_pipeline/serve_graph_api.py`
- 交互方式：HTTP + SSE

2. PDF 解析 + 实体抽取异步流水线（Async Pipeline）
- 提交入口：`POST /v1/pipeline/parse-extract`
- 状态/结果/事件：`/v1/jobs/*`
- 核心后端：`scripts/smj_pipeline/serve_async_pipeline_api.py`
- 执行方式：Celery 或 inline

3. 数据构建与离线工具链（Dataset / Extraction / Build）
- 文献基线审计、构建、DB 核查
- 抽取 MVP 运行
- 图谱视图构建与桌面启动
- 主要入口：`scripts/smj_pipeline/*.py`

---

## 2. 端到端能力清单（按用户可感知功能）

### 2.1 图谱检索与浏览（已线上可用）

入口：
- `GET /frontend/`
- `GET /graph/full`
- `GET /graph/overview`
- `GET /graph/neighborhood`
- `GET /graph/search`
- `GET /variable/{id}`
- `GET /paper/{paper_id_or_doi}`

用户价值：
- 3D 图谱浏览、变量检索、关系查看、论文证据追溯。
- 从图谱节点直接跳转 Chat，并带 `from_node` 上下文。

当前前端行为（as-is）：
- 仅点击节点索引项触发节点切换。
- 节点详情、关系详情分区展示。
- 展示孤立节点清单及原因（如 `definition_only`、`no_relation_extracted`）。

### 2.2 Chat 双模式问答（Fast / Agent）

入口：
- `POST /chat/sessions`
- `GET /chat/sessions`
- `GET /chat/sessions/{session_id}`
- `POST /chat/sessions/{session_id}/messages`
- `GET /chat/sessions/{session_id}/stream?message_id=...`

模式：
- `fast`：query 改写 + 三路召回（keyword/vector/graph）+ 生成回答
- `agent`：多步工具调用 loop（只读工具）+ 总结回答

流式协议：
- SSE 事件：`started | delta | citation | tool_call | completed | failed`
- 前端策略：SSE 主通道 + 自动重连 + 会话状态轮询兜底（防止 running 卡住）

### 2.3 异步 PDF 解析与实体抽取 Pipeline

入口：
- `POST /v1/pipeline/parse-extract`（上传 PDF）
- `GET /v1/jobs/{job_id}`（状态）
- `GET /v1/jobs/{job_id}/result`（结果）
- `POST /v1/jobs/{job_id}/cancel`（取消）
- `GET /v1/jobs/{job_id}/events`（SSE）

阶段：
1. `accepted`
2. `parse_pdf`（MinerU 单文件链路）
3. `extract_entities`
4. `finalize`
5. `completed/failed/cancelled`

产物：
- `outputs/runs/<job_id>/input|parse|extract|result.json`

### 2.4 文献检索与回答 API

入口：
- `POST /literature/import`
- `GET /literature/search`
- `POST /literature/answer`

能力：
- 文献切分、向量与关键词召回、融合检索、问答生成。
- 可与 Chat Fast 模式联动作为检索源。

### 2.5 数据集审计与构建（离线）

入口（CLI）：
- `run_literature_dataset_tools.py dataset-audit`
- `run_literature_dataset_tools.py dataset-build-base`
- `run_literature_dataset_tools.py db-check-mysql|db-check-pg|db-check-summary`

价值：
- 生成可抽取的基线数据集，评估质量、去重/去乱码、核查数据库全文覆盖。

### 2.6 抽取 MVP 与图谱构建（离线/批处理）

入口（CLI）：
- `run_extraction_mvp.py`
- `build_storage_pdf_v4_manifest.py` / `run_mineru_*` / `build_graph_views*`（按现有流程）
- `app_launcher.py`（桌面入口）

价值：
- 从原始文档到结构化关系，再到前端图谱视图与服务启动。

---

## 3. 用户地图（User Map）

## 3.1 用户地图 A：研究用户（图谱探索 -> 问答）

目标：快速从变量关系中得到可引用答案。

路径：
1. 打开 `/frontend/` 查看图谱。
2. 点击节点索引或 3D 节点查看节点详情/关系详情。
3. 点击“打开 chat”，进入 `/frontend/chat/`。
4. 提问，选择 `fast` 或 `agent`。
5. 前端接收 SSE 流式结果，展示引用。
6. 必要时切回图谱继续探索。

成功判定：
- 在一个会话中得到 `completed` 终态回答，且引用可见。

异常分支：
- SSE 短暂断开：自动重连 + 状态轮询兜底。
- provider/model 参数非法：返回 4xx 并前端提示。

## 3.2 用户地图 B：数据工程用户（上传 PDF -> 异步任务）

目标：将单个 PDF 端到端解析并抽取结果。

路径：
1. `POST /v1/pipeline/parse-extract` 上传 PDF。
2. 获得 `job_id`、`sse_url`、`result_url`。
3. 监听 `/v1/jobs/{id}/events` 或轮询 `/v1/jobs/{id}`。
4. 完成后读取 `/v1/jobs/{id}/result`。
5. 下载或消费 `outputs/runs/<job_id>/` 产物。

成功判定：
- `status=completed` 且 `result.json` 可读。

异常分支：
- 解析失败：`failed` + `error_code`（例如 mineru 相关错误）。
- 中途取消：`cancelled`。

## 3.3 用户地图 C：知识库运维用户（文献导入 -> 检索质量验证）

目标：把新文献导入检索系统并验证可检索性。

路径：
1. 构建 manifest。
2. `POST /literature/import` 导入。
3. `GET /literature/search` 检查召回。
4. `POST /literature/answer` 检查回答与引用。
5. 联调 Chat Fast 模式，验证端到端质量。

成功判定：
- 检索有命中，回答带 citations，可复现实验问题。

## 3.4 用户地图 D：质量保障用户（测试回归）

目标：确保核心链路与异常链路可回归。

路径：
1. 运行 API 合约测试（chat/graph/async pipeline）。
2. 运行浏览器 E2E（graph -> chat -> stream -> citation -> back）。
3. 运行全仓测试。

成功判定：
- 全量测试通过（当前基线：`87/87`）。

---

## 4. 核心端到端链路（关键路径）

### 路径 P1：图谱到问答
- `/frontend/` -> 选择变量 -> `/frontend/chat/?from_node=...` -> 提问 -> SSE `completed` -> 引用展示

### 路径 P2：异步处理
- 上传 PDF -> 获取 `job_id` -> 阶段推进（parse/extract/finalize）-> 结果可读

### 路径 P3：知识库刷新
- 导入文献 -> 文献检索/回答 -> Chat Fast 模式引用同源验证

---

## 5. 测试覆盖映射（已存在）

主要测试文件：
- `tests/test_graph_chat_playwright_e2e.py`
- `tests/test_chat_api_endpoints.py`
- `tests/test_serve_graph_api.py`
- `tests/test_async_pipeline_api.py`
- `tests/test_async_pipeline_execution.py`
- 以及全仓 `tests/test_*.py`

覆盖重点：
- Graph + Chat 导航、会话、消息、SSE 完成/失败、引用渲染
- Chat 参数校验与 4xx 路径
- Graph/Literature API 回归
- Async pipeline 提交、状态、取消、结果

---

## 6. 当前已知风险与注意事项

1. 数据语义一致性风险
- 部分变量存在“有定义但无关系边”现象，会出现孤立节点。
- 当前前端已显示孤立原因，但根因在抽取覆盖。

2. 流式稳定性风险
- 网络抖动或 SSE 中断可能导致前端长时间 running。
- 当前已采用重连 + 会话状态兜底，建议继续做长连接压测。

3. 文档与实现漂移风险
- 部分旧文档（例如早期默认前端目录）与现实现可能不一致。
- 本文以代码与测试行为为准。

---

## 7. 建议的统一验收脚本（人工）

1. 启动服务：
```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013
```

2. 图谱与 Chat 手工冒烟：
- 打开 `http://127.0.0.1:8013/frontend/`
- 点击变量 -> 跳 chat -> 提问 -> 观察自动完成与引用

3. 自动化回归：
```powershell
uv run python -m unittest tests.test_graph_chat_playwright_e2e -v
uv run python -m unittest discover -s tests -p "test_*.py"
```

---

## 8. 快速索引

- 图谱+Chat 服务：`scripts/smj_pipeline/serve_graph_api.py`
- 异步 Pipeline 服务：`scripts/smj_pipeline/serve_async_pipeline_api.py`
- Chat 编排服务：`scripts/smj_pipeline/chat_service.py`
- 图谱前端：`frontend/graph_3d/index.html`
- Chat 前端：`frontend/chat_embed/index.html`, `frontend/chat_embed/app.js`
