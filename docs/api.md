# 图谱 API 文档

基础说明：
- 服务脚本：`scripts/smj_pipeline/serve_graph_api.py`
- 默认地址：`http://127.0.0.1:8013`
- 响应编码：`application/json; charset=utf-8`

## 1. GET /graph/full

用途：
- 返回全量节点与全量边，供前端一次性加载。

响应示例：
```json
{
  "meta": {
    "total_rows": 1599,
    "success_rows": 1599,
    "failed_rows": 0,
    "node_count": 3592,
    "edge_count": 3212,
    "paper_count": 1599,
    "year_range": {"min": 1994, "max": 2024}
  },
  "nodes": [
    {
      "id": "var::strategic-investment",
      "type": "variable",
      "label": "strategic_investment",
      "name": "strategic_investment",
      "first_year": 2019,
      "citation_stats": {
        "max_citation_count": null,
        "mean_citation_count": null
      }
    }
  ],
  "edges": [
    {
      "id": "edge::10-1002-smj-3050::strategic-investment::ceo-compensation::0",
      "source": "var::strategic-investment",
      "target": "var::ceo-compensation",
      "paper_id": "10.1002/smj.3050",
      "doi": "10.1002/smj.3050",
      "relation_type": "moderation",
      "relation_form": "linear",
      "direction": "positive",
      "display_effect_class": "positive",
      "verification": "supported",
      "strength": 1.0,
      "evidence_anchor": "Hypothesis 1",
      "paper_year": 2019,
      "citation_stats": {
        "paper_citation_count": null
      }
    }
  ]
}
```

说明：
- `display_effect_class` 由后端统一映射，取值仅为：`positive|negative|nonlinear`。
- 映射规则：`relation_form=nonlinear`，或 `direction` 为 `u_shape/inverted_u/non_directional/non_significant` 时，归类为 `nonlinear`。
- `relation_type` / `relation_type_std`：关系机制类型（工程标准枚举），常见值：`direct`（直接效应）、`moderation`（调节效应）、`mediation`（中介机制）、`interaction`、`nonlinear_effect`。
- `relation_type_raw`：模型原始关系类型文本，保留用于审计。
- `evidence_section`：证据章节（对应后端兼容字段 `evidence_anchor`）。

## 2. GET /graph/overview

用途：
- 返回预计算概览子图。

响应字段：
- `meta`：元信息
- `nodes`：概览节点
- `edges`：概览边

## 3. GET /graph/search?q=<keyword>&limit=<n>

用途：
- 按节点 `label/name` 模糊搜索。

参数：
- `q`：关键字（必填）
- `limit`：返回上限（默认 `20`）

响应：
```json
{
  "nodes": []
}
```

## 4. GET /graph/neighborhood

用途：
- 以指定节点为中心获取邻域子图。

参数：
- `node_id`：节点 ID（必填）
- `hops`：跳数（默认 `1`）
- `limit_nodes`：节点上限（默认 `350`）
- `limit_edges`：边上限（默认 `900`）

成功响应：
- `node_id`
- `nodes`
- `edges`

失败响应：
- 节点不存在时返回 `404`
```json
{
  "error": "node_not_found",
  "node_id": "var::missing"
}
```

## 5. GET /paper/{paper_id}

用途：
- 查询论文详情（relations/hypotheses/citations 等）。

`relations` 可能包含扩展字段：
- `source_aliases: string[]`
- `target_aliases: string[]`
- `unresolved_abbr: boolean`（主名仍为简称且未解析时为 true）
- `abbr_form: string`（未解析简称原文，如 `TMT`）
- `name_resolution_source: prompt|postprocess|fallback`
- `source_canonical_var_id: string`
- `target_canonical_var_id: string`
- `relation_form: linear|nonlinear`

论文级扩展字段：
- `paper_domains: string[]`
- `offline_html_path: string`（本地离线 HTML）
- `article_url: string`（在线页面）
- `publication_date: string`
- `online_date: string`
- `publication_year: number|null`
- `paper_citation_count: number|null`

失败响应：
- 论文不存在时返回 `404`
```json
{
  "error": "paper_not_found",
  "paper_id": "10.1002/unknown"
}
```

## 6. 静态页面

- `GET /frontend/`：返回图谱前端主页。
- `GET /`：返回主页内容（等效 `index.html`）。

## 7. GET /variable/{var_id}

用途：
- 获取某个变量实体涉及的论文列表与关系提及摘要。

响应字段：
- `node`：变量节点信息
- `paper_count`：提及论文数
- `papers[]`：每篇论文的 `paper_id/doi/publication_year/open_local_html/open_online_url/mentions`

## 8. GET /graph/search

用途：
- 混合检索（关键词 + 本地向量）并支持模式切换。

参数：
- `mode=variable|paper`
- `query`：查询词
- `keyword_weight`：关键词权重（0~1）
- `vector_weight`：向量权重（0~1）
- `limit`：返回条数

响应：
- `results[]`：中等密度卡片信息，包含前因/后果变量、关系摘要、论文打开链接等。
