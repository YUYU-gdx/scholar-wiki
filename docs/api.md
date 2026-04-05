# Graph API 文档

基础说明:
- 服务脚本: `scripts/smj_pipeline/serve_graph_api.py`
- 默认地址: `http://127.0.0.1:8013`
- 响应编码: `application/json; charset=utf-8`

## 1. GET /graph/full

用途:
- 返回全量节点与全量边，用于前端一次性加载。

响应示例:
```json
{
  "meta": {
    "total_rows": 1599,
    "success_rows": 1599,
    "failed_rows": 0,
    "node_count": 3592,
    "edge_count": 3212,
    "paper_count": 1599
  },
  "nodes": [
    {
      "id": "var::strategic-investment",
      "type": "variable",
      "label": "strategic_investment",
      "name": "strategic_investment"
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
      "evidence_anchor": "Hypothesis 1"
    }
  ]
}
```

说明:
- `display_effect_class` 由后端统一映射，仅取 `positive|negative|nonlinear` 三类，用于前端颜色。
- 规则: `relation_form=nonlinear` 或方向为 `u_shape/inverted_u/non_directional/non_significant` 时归为 `nonlinear`。

## 2. GET /graph/overview

用途:
- 返回预计算的概览子图。

响应:
- `meta`: 元信息
- `nodes`: 概览节点
- `edges`: 概览边

## 3. GET /graph/search?q=<keyword>&limit=<n>

用途:
- 按节点 `label/name` 模糊搜索。

参数:
- `q`: 关键字，必填
- `limit`: 返回上限，默认 `20`

响应:
```json
{
  "nodes": []
}
```

## 4. GET /graph/neighborhood

用途:
- 以某个节点为中心获取邻域子图。

参数:
- `node_id`: 节点 ID，必填
- `hops`: 跳数，默认 `1`
- `limit_nodes`: 节点上限，默认 `350`
- `limit_edges`: 边上限，默认 `900`

成功响应:
- `node_id`
- `nodes`
- `edges`

失败响应:
- 节点不存在时返回 `404`
```json
{
  "error": "node_not_found",
  "node_id": "var::missing"
}
```

## 5. GET /paper/{paper_id}

用途:
- 查询论文详情数据（relations/hypotheses/citations 等）。

返回中的 `relations` 可能包含以下扩展字段:
- `source_aliases: string[]`
- `target_aliases: string[]`
- `source_canonical_var_id: string`
- `target_canonical_var_id: string`
- `relation_form: linear|nonlinear`
- 论文级别字段: `paper_domains: string[]`

失败响应:
- 论文不存在时返回 `404`
```json
{
  "error": "paper_not_found",
  "paper_id": "10.1002/unknown"
}
```

## 6. 静态页面

- `GET /frontend/` 返回图谱前端主页。
- `GET /` 会重定向逻辑到主页内容（同 `index.html`）。
