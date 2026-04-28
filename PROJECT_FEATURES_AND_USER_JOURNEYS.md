# kn-gragh 功能全景与用户旅程文档

> 本文档梳理 kn-gragh 项目的全部功能模块、系统入口、用户角色及端到端旅程。  
> 适用于产品对齐、新人 onboarding、联调测试与运维参考。  
> 最后更新：2026-04-24

---

## 一、系统全景

kn-gragh 是一个面向学术文献的知识图谱构建与问答平台，核心能力围绕**供应链领域**（可扩展）的论文解析、实体抽取、关系构建、可视化浏览与智能问答。

系统可划分为 **6 大功能域**：

| 功能域 | 定位 | 用户角色 |
|--------|------|----------|
| **图谱浏览** | 3D 交互式知识图谱可视化 | 研究用户 |
| **Chat 问答** | 基于图谱与文献的智能问答 | 研究用户 |
| **异步 Pipeline** | PDF 解析 → 实体抽取的异步任务流 | 数据工程用户 |
| **文献检索** | 段落级语义检索与问答生成 | 知识库运维用户 |
| **离线批处理** | 大规模论文抽取、数据集构建、Run 管理 | 数据工程 / 运维用户 |
| **桌面应用** | Electron 封装的一体化客户端 | 所有用户 |

---

## 二、前端入口与界面矩阵

项目存在 **5 个前端入口**，服务于不同场景：

| 入口路径 | 技术栈 | 用途 | 状态 |
|----------|--------|------|------|
| `/frontend/` (`graph_3d/`) | 原生 HTML + JS + Three.js | 3D 图谱浏览主入口 | 生产可用 |
| `/frontend/chat/` (`chat_embed/`) | 原生 HTML + JS | Chat 问答页面（嵌入/独立） | 生产可用 |
| `/frontend/workbench/` (`workbench_spa/`) | React (CDN) + GoldenLayout | 多面板工作台（图谱+Chat+导入+搜索） | 生产可用 |
| `frontend/chat_spa/` | Vite + React | 现代化 Chat SPA（独立部署） | 开发中 |
| `frontend/desktop_shell/` | Electron | 桌面客户端 | 生产可用 |

**桌面应用行为**：
- Electron 主进程自动启动后端服务（`serve_graph_api.py --port 8013`）
- 默认加载 `/frontend/workbench/`
- 支持环境变量 `KN_GRAPH_PORT` 自定义端口

---

## 三、功能模块详解

### 3.1 图谱浏览（Graph 3D）

**核心能力：**
- 3D 力导向图谱渲染，支持旋转、缩放、拖拽
- 节点按类型着色（变量节点、论文节点）
- 边按关系效果着色（正向 / 负向 / 非线性）
- 节点检索与索引列表
- 节点详情面板（定义、关系、论文证据）
- 孤立节点识别与原因展示
- 从节点直接跳转 Chat 并携带上下文

**API 支撑：**
- `GET /graph/full` — 全量图数据
- `GET /graph/overview` — 预计算概览子图（首屏提速）
- `GET /graph/neighborhood?node_id=xxx&hops=1` — 局部邻域
- `GET /graph/search?query=xxx&mode=variable|paper` — 混合检索
- `GET /variable/{var_id}` — 变量详情与论文聚合
- `GET /paper/{paper_id_or_doi}` — 单篇论文详情

**数据来源：**
- 默认读取 `outputs/runs/active.json` 指向的 `graph_views.json`
- 限制在 `outputs/smj_supply_chain_batch` 目录下（可 `--allow-non-supply-chain` 覆盖）

---

### 3.2 Chat 双模式问答

**Fast 模式：**
- 查询改写（LLM 重写为学术检索式）
- 三路召回：关键词 BM25 + 向量 RAG + 图谱节点检索
- 证据段落去重与排序
- LLM 生成带引用标记的回答
- SSE 流式输出

**Agent 模式：**
- 多步工具调用循环（只读工具）
- 集成 Codex CLI Agent（JSON-RPC over stdio）
- 工具包括：文献检索、图谱搜索、Weaviate 查询
- 自动审批 MCP 工具调用
- 实时展示工具调用轨迹

**会话管理：**
- 创建 / 列表 / 获取 / 删除 / 恢复会话
- 软删除 + 撤销窗口（默认 5 秒）
- 消息历史持久化（PostgreSQL 或内存）
- SSE 事件流：`started | delta | citation | tool_call | completed | failed`

**API 支撑：**
- `POST /chat/sessions` — 创建会话
- `GET /chat/sessions` — 列表
- `GET /chat/sessions/{id}` — 详情与历史
- `POST /chat/sessions/{id}/messages` — 提交消息
- `GET /chat/sessions/{id}/stream?message_id=xxx` — SSE 流

---

### 3.3 异步 PDF 解析与实体抽取 Pipeline

**任务阶段：**
1. `accepted` — 任务入队
2. `parse_pdf` — MinerU 解析 PDF 为 HTML（进度 5%-45%）
3. `extract_entities` — LLM 抽取结构化关系（进度 55%-90%）
4. `finalize` — 结果整理、可选导入文献库（进度 95%-100%）
5. `completed | failed | cancelled` — 终态

**执行方式：**
- **Celery**（默认）：Redis 作 broker，支持分布式 Worker
- **Inline**：本地线程执行（调试/单节点）

**产物：**
- `outputs/runs/<job_id>/input/` — 上传的原始 PDF
- `outputs/runs/<job_id>/parse/` — MinerU 解析产物
- `outputs/runs/<job_id>/extract/` — 抽取结果、评测报告
- `outputs/runs/<job_id>/result.json` — 最终汇总

**API 支撑：**
- `POST /v1/pipeline/parse-extract` — 提交单文件
- `POST /v1/pipeline/parse-extract/batch` — 批量提交
- `GET /v1/jobs/{job_id}` — 状态查询
- `GET /v1/jobs/{job_id}/result` — 结果获取
- `POST /v1/jobs/{job_id}/cancel` — 取消任务
- `POST /v1/jobs/{job_id}/retry` — 重试失败任务
- `GET /v1/jobs/{job_id}/events` — SSE 事件流

---

### 3.4 文献检索与问答

**核心能力：**
- 文献清单导入（JSONL 格式）
- 文档级 / 段落级 / 句子级切分
- 双路召回：BM25 关键词 + 向量 Embedding
- RRF 融合排序
- 基于召回结果生成回答（GLM Chat）

**存储后端：**
- Weaviate（向量数据库）
- PostgreSQL（结构化数据）

**API 支撑：**
- `POST /literature/import` — 导入文献清单
- `GET /literature/search?query=xxx` — 双路检索
- `POST /literature/answer` — 检索 + 生成回答

---

### 3.5 离线批处理工具链

#### 3.5.1 数据集审计与构建

| 工具 | 命令 | 功能 |
|------|------|------|
| **目录审计** | `run_literature_dataset_tools.py dataset-audit` | 扫描 outputs 目录，生成审计报告 |
| **基线构建** | `run_literature_dataset_tools.py dataset-build-base` | 去重、去乱码、去空文件、成本估算 |
| **MySQL 核查** | `run_literature_dataset_tools.py db-check-mysql` | 核查 MySQL 全文字段完整性 |
| **PG 核查** | `run_literature_dataset_tools.py db-check-pg` | 核查 PostgreSQL 全文字段完整性 |
| **核查汇总** | `run_literature_dataset_tools.py db-check-summary` | 合并 MySQL + PG 核查结果 |

**产物：**
- `outputs/literature_base/base_dataset.jsonl` — 清洗后数据集
- `outputs/literature_base/rejected_dataset.jsonl` — 被拒数据
- `outputs/literature_base/cost_estimate.md` — 成本估算
- `outputs/literature_base/db_fulltext_check_*.json` — DB 核查报告

#### 3.5.2 抽取 MVP 运行器

**输入：** JSONL 清单，每行包含 `html` 或路径字段
**管线：** 分类（Class A/B/C）→ 定位 → 抽取 → 校验 → （可选）入库
**输出：**
- `raw_llm_outputs.jsonl` — 原始模型输出
- `review_queue.jsonl` — 待审核队列
- `acceptance_report.md` — 验收报告

**启动命令：**
```bash
uv run python scripts/smj_pipeline/run_extraction_mvp.py \
  --input-manifest path/to/manifest.jsonl \
  --sample-size 100 \
  --llm-provider zhipu \
  --llm-model glm-4.5-flash
```

#### 3.5.3 Run 管理（批量实验）

**概念：** 每次批量抽取为一个 "Run"，隔离目录，支持切换与回滚。

| 操作 | 命令 | 说明 |
|------|------|------|
| **提交 Batch** | `run_latest_n_batch.py --n 30` | 提交最新 N 篇论文 |
| **完结 Run** | `finalize_batch_run.py --run-id xxx` | 构建 artifact + graph_views |
| **激活 Run** | `activate_run.py --run-id xxx` | 切换 active.json 指针 |
| **列表** | `list_runs.py` | 查看所有 Run 状态 |
| **供应链筛选** | `filter_manifest_supply_chain.py` | 按词典筛选供应链论文 |
| **全量推理** | `run_full_batch_inference.py` | 提交批量推理任务 |

**目录结构：**
```
outputs/runs/
├── active.json              # 当前激活的 run 指针
├── <run_id>/
│   ├── manifest_input.jsonl
│   ├── frontend_artifact.json
│   ├── graph_views.json
│   └── run_meta.json
```

#### 3.5.4 图谱视图构建

从 `frontend_artifact.json` 构建优化的服务视图：
```bash
uv run python scripts/smj_pipeline/build_graph_views.py \
  --input-json .../frontend_artifact.json \
  --output-json .../graph_views.json
```

增加索引：
- `edge_index_by_node` — 快速邻域查询
- `overview` — 预计算子图
- `paper_map` — 双 key 索引（paper_id + doi）

---

### 3.6 桌面启动器

**功能按钮：**
1. **导入文件并解析** — 选择前端 artifact JSON，构建 graph_views
2. **导入 PostgreSQL** — 输入 DSN，导出 artifact 并构建视图
3. **打开展示** — 启动本地服务并自动打开浏览器

**启动命令：**
```bash
uv run python scripts/smj_pipeline/app_launcher.py
```

---

## 四、用户旅程（User Journeys）

### 旅程 A：研究用户 — 图谱探索与问答

> **目标：** 快速从变量关系网络中获取可引用的研究答案。

```
[启动服务]
    │
    ▼
打开浏览器 → http://127.0.0.1:8013/frontend/
    │
    ▼
[图谱浏览阶段]
    │
    ├── 查看 3D 图谱全貌
    ├── 在节点索引中搜索关键词
    ├── 点击节点查看详情面板
    │       ├── 变量定义与来源论文
    │       ├── 入边/出边关系列表
    │       └── 调节效应与交互效应
    └── 点击"打开 Chat"按钮
            │
            ▼
            跳转 /frontend/chat/?from_node=变量名
            │
            ▼
[Chat 问答阶段]
    │
    ├── 选择模式：Fast / Agent
    ├── 输入研究问题
    ├── 观察 SSE 流式输出
    │       ├── Fast：直接看到带引用标记的回答
    │       └── Agent：看到工具调用轨迹 → 最终回答
    ├── 点击引用编号查看证据段落
    └── （可选）切回图谱继续探索
    │
    ▼
[成功判定]
    会话状态 = completed，回答中包含 [1][2]... 引用标记
```

**异常分支：**
- SSE 断开 → 前端自动重连 + 状态轮询兜底
- 模型服务不可用 → 降级为基于已有证据的摘要回答
- 检索无命中 → 显示"未检索到直接证据"提示

---

### 旅程 B：数据工程用户 — PDF 解析与抽取

> **目标：** 将单篇 PDF 端到端解析并抽取结构化关系。

```
[启动异步 API]
    │
    ▼
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --port 8021
    │
    ▼
[提交任务]
    │
    ├── 方式 1：前端上传（Workbench 导入面板）
    └── 方式 2：API 调用
            POST /v1/pipeline/parse-extract
            multipart/form-data: file=paper.pdf, library_id=supply_chain
    │
    ▼
[获取 job_id]
    响应：{ job_id, sse_url, result_url, status: "queued" }
    │
    ▼
[监听进度]
    │
    ├── SSE 流：/v1/jobs/{job_id}/events
    │       ├── event: accepted
    │       ├── event: stage_started (parse_pdf)
    │       ├── event: stage_progress (5% → 45%)
    │       ├── event: stage_started (extract_entities)
    │       ├── event: stage_progress (55% → 90%)
    │       ├── event: stage_started (finalize)
    │       └── event: completed
    └── 或轮询：GET /v1/jobs/{job_id}
    │
    ▼
[获取结果]
    GET /v1/jobs/{job_id}/result
    │
    ▼
[产物消费]
    │
    ├── 读取 result.json（结构化抽取结果）
    ├── 读取 extract/acceptance_report.md（质量报告）
    └── （可选）自动导入文献库，后续可在 Chat 中检索
    │
    ▼
[成功判定]
    status = completed，result.json 包含 main_effects / moderations / interactions
```

**异常分支：**
- 解析失败 → status = failed，error_code = mineru_xxx
- 用户取消 → POST /v1/jobs/{job_id}/cancel → status = cancelled
- 重试 → POST /v1/jobs/{job_id}/retry（仅 failed/cancelled 可重试）

---

### 旅程 C：知识库运维用户 — 文献导入与检索验证

> **目标：** 将新文献导入检索系统并验证可检索性。

```
[准备数据]
    │
    ▼
构建 manifest.jsonl（每行：paper_id, doi, title, source_path）
    │
    ▼
[导入文献]
    │
    POST /literature/import
    { manifest_path: ".../manifest.jsonl", library_id: "supply_chain" }
    │
    ▼
[等待索引]
    │
    响应：{ imported_count, sentence_count, paragraph_count, document_count }
    │
    ▼
[验证召回]
    │
    ├── GET /literature/search?query=supply+chain+resilience&library_id=supply_chain
    └── 检查 keyword_hits + rag_hits + merged_hits 非空
    │
    ▼
[验证回答质量]
    │
    POST /literature/answer
    { query: "What factors affect supply chain resilience?", library_id: "supply_chain" }
    │
    ▼
[联调 Chat]
    │
    在 Chat Fast 模式中提问同一问题
    验证 citations 与 /literature/search 召回结果同源
    │
    ▼
[成功判定]
    检索有命中，回答带 citations，问题可复现实验
```

---

### 旅程 D：数据工程用户 — 批量 Run 管理

> **目标：** 管理大规模批量抽取实验，支持版本切换。

```
[筛选供应链论文]
    │
    ▼
uv run python scripts/smj_pipeline/filter_manifest_supply_chain.py \
  --input-manifest .../manifest_from_success.jsonl \
  --lexicon prompt/supply_chain_lexicon.md \
  --output-dir outputs/smj_supply_chain_batch
    │
    ▼
[提交批量推理]
    │
    ▼
uv run python scripts/smj_pipeline/run_full_batch_inference.py \
  --input-manifest .../manifest_input.jsonl \
  --output-dir outputs/smj_supply_chain_batch/<run_id> \
  --model glm-4-plus --class-a-only --submit
    │
    ▼
[等待批次完成]
    │
    （监控外部 Batch 服务状态）
    │
    ▼
[完结 Run]
    │
    ▼
uv run python scripts/smj_pipeline/finalize_batch_run.py \
  --run-id <run_id> --activate
    │
    ▼
[产物检查]
    │
    outputs/smj_supply_chain_batch/<run_id>/
    ├── frontend_artifact.json      # 前端产物
    └── graph_views.json            # 服务视图
    │
    ▼
[激活与切换]
    │
    ├── 当前 Run：active.json 自动指向新 run
    └── 回滚：activate_run.py --run-id <old_run_id>
    │
    ▼
[启动服务验证]
    │
    ▼
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013
打开浏览器验证图谱与 Chat
```

---

### 旅程 E：质量保障用户 — 测试回归

> **目标：** 确保核心链路与异常链路可回归验证。

```
[启动全量测试]
    │
    ▼
uv run python -m unittest discover -s tests -p "test_*.py" -v
    │
    ▼
[测试分层]
    │
    ├── 单元测试
    │       ├── test_extraction_schemas.py      # 抽取 Schema 校验
    │       ├── test_extraction_extractor.py    # 抽取核心逻辑
    │       ├── test_storage_postgres_repo.py   # PG 存储
    │       ├── test_provider_registry.py       # LLM Provider
    │       └── ...
    ├── API 合约测试
    │       ├── test_serve_graph_api.py         # Graph API
    │       ├── test_chat_api_endpoints.py      # Chat API
    │       └── test_async_pipeline_api.py      # Pipeline API
    └── E2E 浏览器测试
            ├── test_graph_chat_playwright_e2e.py
            │       ├── 图谱加载 → 点击节点 → 跳转 Chat
            │       ├── Chat 提问 → SSE 完成 → 引用展示
            │       └── 图谱拖拽交互
            └── test_workbench_playwright_e2e.py
                    └── Workbench 多面板切换
    │
    ▼
[成功判定]
    全量测试通过（当前基线：87/87）
```

---

## 五、数据流全景

```
┌─────────────────────────────────────────────────────────────────────┐
│                           数据源层                                   │
│  PDF 文件  │  HTML 文件  │  JSONL 清单  │  Wiley 在线全文  │  ...   │
└───────────┬─────────────┬──────────────┬──────────────────┬─────────┘
            │             │              │                  │
            ▼             ▼              ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         解析与抽取层                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ MinerU 解析   │  │ LLM 抽取     │  │ 分类 / 定位 / 校验        │  │
│  │ PDF → HTML   │  │ HTML → JSON  │  │ Class A/B/C              │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          存储层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ PostgreSQL   │  │ Weaviate     │  │ 文件系统                  │  │
│  │ 结构化数据   │  │ 向量检索     │  │ graph_views.json         │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         服务与 API 层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Graph API    │  │ Chat API     │  │ Async Pipeline API       │  │
│  │ (8013)       │  │ (8013)       │  │ (8021)                   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         前端展示层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Graph 3D     │  │ Chat Embed   │  │ Workbench / Electron     │  │
│  │ 图谱浏览     │  │ 问答交互     │  │ 一体化工作台             │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、关键配置与环境变量

### 6.1 服务启动配置

| 变量 | 用途 | 示例 |
|------|------|------|
| `KN_GRAPH_PORT` | Graph API 端口 | `8013` |
| `CHAT_STORE_DSN` | Chat 消息存储 | `postgresql://user:pass@localhost/kn_graph` |
| `PIPELINE_JOB_STORE_DSN` | Pipeline 任务存储 | 同上 |
| `PIPELINE_EXECUTOR` | 执行器类型 | `celery` / `inline` |
| `PIPELINE_REDIS_URL` | Celery Broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | 智谱 API 密钥 | `xxx.xxx` |
| `NVIDIA_API_KEY` | NVIDIA API 密钥 | `nvapi-xxx` |
| `WEAVIATE_URL` | Weaviate 地址 | `http://127.0.0.1:8090` |

### 6.2 LLM Provider 配置

统一配置文件：`config/llm_providers.json`

支持 Provider：
- `zhipu`（智谱，默认）
- `nvidia`（NVIDIA NIM）
- `openai_compatible`（DeepSeek 等）

环境变量覆盖：`LLM_PROVIDER_CONFIG_PATH`

---

## 七、故障排查速查表

| 现象 | 排查路径 | 解决建议 |
|------|----------|----------|
| 图谱空白 | 检查 `active.json` → 确认 `graph_views.json` 存在 | 运行 `build_graph_views.py` 或 `finalize_batch_run.py` |
| Chat 无响应 | 检查 SSE 连接 → 查看 `chat_messages` 表状态 | 检查 LLM API Key、Provider 配置 |
| Pipeline 卡住 | 检查 Celery Worker 是否运行 | 切换 `PIPELINE_EXECUTOR=inline` 调试 |
| 检索无结果 | 检查 Weaviate 连接、文献是否已导入 | 重新运行 `/literature/import` |
| 节点孤立 | 查看 `isolated_nodes` 列表 → 检查抽取覆盖率 | 补充 Class A 论文抽取 |
| 数据丢失 | 检查是否使用了 InMemory 存储 | 配置 `CHAT_STORE_DSN` 到 PostgreSQL |

---

*本文档基于代码、测试与现有文档整理，以运行时行为为准。*
