# 图谱 API 文档（新版结构）

基础说明：
- 服务脚本：`scripts/smj_pipeline/serve_graph_api.py`
- 默认地址：`http://127.0.0.1:8013`

## 1. GET /graph/full
返回全量节点、主效应边（`main_effects` 投影）与调节关系（`moderation_links`）。

## 2. GET /graph/overview
返回预计算概览子图。

## 3. GET /graph/search
参数：
- `mode=variable|paper`
- `query` 或 `q`
- `keyword_weight`、`vector_weight`
- `limit`

## 4. GET /graph/neighborhood
参数：
- `node_id`
- `hops`（默认 1）
- `limit_nodes`、`limit_edges`

## 5. GET /paper/{paper_id_or_doi}
返回论文详情（新版字段）：
- `extractability_status` / `paper_type`
- `extractability_reason` / `extractability_evidence_section`
- `variable_definitions[]`
- `main_effects[]`
- `interactions[]`
- `context_variables[]`
- `operationalization{}`
- 以及 `offline_html_path`、`article_url`、`publication_year` 等元数据。

## 6. GET /variable/{var_id}
返回变量详情与按论文聚类的结构化信息：
- `paper_count_total` / `paper_count_edge` / `paper_count_moderation` / `paper_count_interaction`
- `paper_groups[]`（每篇论文一组）
  - `paper_id` / `doi` / `publication_year`
  - `open_local_html` / `open_online_url`
  - `concepts[]`（来自 `variable_definitions`）
  - `measurement_methods[]`（来自 `operationalization`）
  - `relations[]`（直接效应/调节效应/统计交互效应）
- 兼容保留：`papers[]`（旧版提及摘要）

## 7. 静态页面
- `GET /frontend/`
- `GET /`
