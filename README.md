# kn-gragh

## 文档入口

- 项目规约总览（建议先看）：`docs/project_spec_index.md`
- Graph API 规约：`docs/api.md`
- 异步端到端 Pipeline API：`docs/async_pipeline_api.md`
- 数据模型规约：`docs/data_model.md`
- 后端合并设计文档：`docs/superpowers/specs/2026-04-30-backend-unification-design.md`

## 启动方式

### 统一主入口（唯一）

```bash
# 统一 API 服务
uv run python -m kn_graph serve --port 8013

# Celery Worker（可选）
uv run python -m kn_graph worker

# MCP 工具服务器
uv run python src/kn_graph/services/kn_mcp_server.py
```

## 测试

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## 关键配置

| 环境变量 | 用途 | 默认值 |
|----------|------|--------|
| `KN_GRAPH_PORT` | 主 API 端口 | `8013` |
| `KN_ASYNC_PIPELINE_PORT` | Pipeline 端口 | `8021` |
| `CHAT_STORE_DSN` | Chat 存储 DSN | 内存 |
| `PIPELINE_JOB_STORE_DSN` | Pipeline 存储 DSN | SQLite |
| `PIPELINE_EXECUTOR` | 执行器类型 | `inline` |
| `PIPELINE_REDIS_URL` | Celery broker | `redis://127.0.0.1:6379/0` |
| `ZHIPU_API_KEY` | 智谱 API 密钥 | — |
| `NVIDIA_API_KEY` | NVIDIA API 密钥 | — |
| `LLM_PROVIDER_CONFIG_PATH` | LLM 配置路径 | `config/llm_providers.json` |
| `CHROMADB_PATH` | ChromaDB 持久化目录 | `{data_dir}/chromadb` |

## LLM Provider 配置

- 配置文件：`config/llm_providers.json`
- 代理注册表：`src/kn_graph/providers/registry.py`
- 覆盖配置：`set LLM_PROVIDER_CONFIG_PATH=path/to/config.json`

## 生产提示词来源

- 当前生产抽取提示词：`prompt/extraction_system_prompt.md`
- 接口通过 `src/kn_graph/services/extraction/prompts.py` 加载

## 后端状态

- **已收口**：后端统一为单 FastAPI 应用（`src/kn_graph`）
- **约束**：`scripts/` 已删除，后端逻辑仅允许位于 `src/kn_graph/`
- **禁止**：不要创建或修改 `frontend/` 目录

## 前端维护策略（已收敛）

- 唯一前端源码目录：`scholarai-workbench/src`
- `frontend/` 视为历史目录（冻结，禁止改动）
- `scholarai-workbench/dist` 为构建产物，不作为开发源码维护
- 日常开发请只在 `scholarai-workbench/src` 修改，并通过 `npm run build` 验证

## 供应链数据源（当前默认）

- 当前默认运行指针：`outputs/runs/active.json`
- 供应链目录：`outputs/smj_supply_chain_batch/`
- 入口脚本默认拒绝非供应链目录，可用 `--allow-non-supply-chain` 覆盖
