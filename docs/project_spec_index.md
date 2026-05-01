# 项目规约总览（入口）

本文档是 `kn-gragh` 的规约导航，帮助快速定位 API、数据模型、运行与提示词约束。

## 1. 核心规约文档
- API 规约：`docs/api.md`
- 文件存储与端口规约：`docs/storage_and_port_conventions.md`
- 数据模型规约：`docs/data_model.md`
- Run 管理：`docs/run_management.md`
- 可复用抽取/评测流程：`docs/reusable_extract_eval_workflow.md`

## 2. 代码事实源（与规约对应）
- API 服务：`scripts/smj_pipeline/serve_graph_api.py`
- 抽取 schema：`scripts/smj_pipeline/extraction/schemas.py`
- 抽取提示词加载：`scripts/smj_pipeline/extraction/prompts.py`
- 生产提示词模板：`prompt/extraction_system_prompt.md`
- PostgreSQL DDL：`scripts/smj_pipeline/storage/schema_postgres.sql`
- 入库脚本：`scripts/smj_pipeline/import_raw_outputs_to_postgres.py`
- 前端产物导出：`scripts/smj_pipeline/export_frontend_artifact_from_postgres.py`
- 图视图构建：`scripts/smj_pipeline/build_graph_views.py`

## 3. 统一口径（当前）
- 逻辑抽取模型以 `main_effects` 为主；存储层仍兼容 `direct_effects` 历史表名。
- API 使用 `graph_views.json` 作为服务读取对象；默认来自 `outputs/runs/active.json` 指向的 run。
- 提示词唯一加载源为 `prompt/` 目录。
- Python 执行统一使用 `uv`。

## 4. 你最常用的排查路径
1. 接口字段不一致：先查 `docs/api.md`，再核对 `serve_graph_api.py`。
2. 前后端字段不一致：先查 `docs/data_model.md` 的 L3/L4，再核对 `export_frontend_artifact_from_postgres.py` 与 `build_graph_views.py`。
3. 模型输出解析异常：查 `prompt/extraction_system_prompt.md` + `extraction/schemas.py`。
4. 入库异常：查 `schema_postgres.sql` + `import_raw_outputs_to_postgres.py`。
