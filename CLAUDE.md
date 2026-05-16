# KN Graph 项目说明

## 运行入口

- 后端服务：`uv run python -m kn_graph serve --port 8013`
- Worker：`uv run python -m kn_graph worker`
- MCP Server（stdio）：`uv run python -m kn_graph mcp-server`
- 单元测试（unittest）：`uv run python -m unittest discover -s tests -p "test_*.py" -v`
- 单元测试（pytest）：`uv run pytest tests/ -v`

## 当前架构

- 唯一后端主链路：`src/kn_graph`
- 应用入口：`src/kn_graph/app.py`
- CLI 入口：`src/kn_graph/__main__.py`
- MCP 服务：`src/kn_graph/services/kn_mcp_server.py`
- Pipeline 运行时：`src/kn_graph/services/pipeline_runtime.py`

## 功能模块

- 路由：`src/kn_graph/routers/`
  - `graph.py`
  - `chat.py`
  - `literature.py`
  - `pipeline.py`
  - `workspace.py`
  - `settings.py`
- 服务：`src/kn_graph/services/`
- 数据模型：`src/kn_graph/models/`

## 关键约束

- 禁止修改 `frontend/`（废弃目录）
- 前端工作目录使用 `scholarai-workbench/`
- Python 命令统一使用 `uv run`
- 不要新增对已删除目录 `scripts/*` 的运行时依赖

## 文献与图谱链路

- 文献导入与解析：`literature_service` + `pipeline_runtime`
- 结构化抽取：`services/extraction/`
- 图谱构建：SQLite/产物链路在 `services/graph_builder.py` 与相关服务中维护

## MCP 说明

- MCP 工具服务通过 stdio 提供 `rag_search`、`graph_variable_neighbors`、`graph_variable_concept_search`
- workspace `.mcp.json` 在应用启动和 agent 启动前都会做自愈修复

## 参考文档

- `docs/project_spec_index.md`
- `docs/api.md`
- `docs/async_pipeline_api.md`
- `docs/data_model.md`
- `docs/superpowers/specs/2026-04-30-backend-unification-design.md`
