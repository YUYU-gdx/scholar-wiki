# KN Graph 项目代理规则

## 流程规范

- 默认流程技能：`using-superpowers`。在本仓库内，代理在执行实现或澄清前，应优先调用并遵循 `using-superpowers`。
- Python 环境与命令执行统一使用 `uv`。
- 严禁要求最终用户手写、粘贴或编辑 JSON 配置；所有用户可配置项必须通过明确的表单控件提供。
- 执行 Bash 命令时，必须始终设置合理的 timeout 参数（毫秒），禁止无超时地阻塞等待。后台服务应使用 `Start-Process` 启动后立即用健康检查轮询确认就绪，而非阻塞在进程输出上。

## 项目概述

KN Graph 是面向学术文献的知识图谱构建与问答平台，核心能力围绕供应链领域论文的解析、实体抽取、关系构建、可视化浏览与智能问答。

## 项目结构

```
kn_gragh/
├── src/kn_graph/                  ← 后端主包（重构中，将替代 scripts/）
├── scripts/smj_pipeline/          ← 当前后端入口（待迁移）
│   ├── serve_graph_api.py          ← 图谱/Chat/文献 API（端口 8013）
│   ├── serve_async_pipeline_api.py ← 异步 Pipeline API（端口 8021）
│   ├── kn_mcp_server.py            ← MCP 工具服务器（stdin/stdout）
│   └── ...                         ← 业务脚本、抽取、数据处理等
├── config/                        ← LLM Provider 配置
├── prompt/                         ← 抽取提示词模板
├── outputs/                        ← 运行产物（graph_views.json 等）
├── tests/                          ← 测试
├── frontend_legacy/                ← 已封存前端（不再维护）
└── docs/                           ← 文档
```

## 启动方式

### 统一 API 服务（目标架构，待实现）

```bash
uv run python -m kn_graph serve --port 8013
```

### 当前启动方式（重构前）

```bash
# 图谱 + Chat + 文献 API
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8013 --views-json outputs/.../graph_views.json --allow-non-supply-chain

# 异步 Pipeline API
uv run python scripts/smj_pipeline/serve_async_pipeline_api.py --host 127.0.0.1 --port 8021

# 桌面启动器（自动启动以上两个服务 + 打开浏览器）
uv run python scripts/smj_pipeline/app_launcher.py
```

### MCP 工具服务器

```bash
uv run python scripts/smj_pipeline/kn_mcp_server.py
```

## 关键配置

| 环境变量 | 用途 | 默认值 |
|----------|------|--------|
| `KN_GRAPH_PORT` | Graph API 端口 | `8013` |
| `KN_ASYNC_PIPELINE_PORT` | 异步 Pipeline 端口 | `8021` |
| `CHAT_STORE_DSN` | Chat 存储 DSN | 内存 |
| `PIPELINE_JOB_STORE_DSN` | Pipeline 存储 DSN | SQLite |
| `PIPELINE_EXECUTOR` | 执行器类型 | `inline` |
| `PIPELINE_REDIS_URL` | Celery broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | 智谱 API 密钥 | — |
| `NVIDIA_API_KEY` | NVIDIA API 密钥 | — |
| `LLM_PROVIDER_CONFIG_PATH` | LLM 配置路径 | `config/llm_providers.json` |
| `WEAVIATE_URL` | Weaviate 地址 | `http://127.0.0.1:8090` |

## 重构状态

- **进行中**：后端合并为单 FastAPI 应用，详见 `docs/superpowers/specs/2026-04-30-backend-unification-design.md`
- **已完成**：`frontend_legacy/` 已封存，不再修改
- **禁止**：不要创建或修改 `frontend/` 目录下的任何内容

## 后端 API 端点概览

### 端口 8013（Graph API — 重构前）

| 域 | 端点数 | 关键路径 |
|----|--------|----------|
| Graph | 6 | `/graph/overview`, `/graph/full`, `/graph/search`, `/graph/neighborhood`, `/paper/{id}`, `/variable/{id}` |
| Chat | 15 | `/chat/sessions/*`, `/chat/codex/*`, `/chat/provider-*` |
| Literature | 4 | `/literature/search`, `/literature/libraries`, `/literature/import`, `/literature/answer` |
| Workspace | 3 | `/api/v2/workspace/layout*` |
| Static | 3 | `/frontend/*` |

### 端口 8021（Pipeline API — 重构前）

| 域 | 端点数 | 关键路径 |
|----|--------|----------|
| Health | 2 | `/healthz`, `/v1/pipeline/health` |
| Jobs | 5 | `/v1/jobs`, `/v1/jobs/{id}`, `/v1/jobs/{id}/result`, `/v1/jobs/{id}/cancel`, `/v1/jobs/{id}/retry` |
| Pipeline | 2 | `/v1/pipeline/parse-extract`, `/v1/pipeline/parse-extract/batch` |
| SSE | 1 | `/v1/jobs/{id}/events` |

## 测试

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```