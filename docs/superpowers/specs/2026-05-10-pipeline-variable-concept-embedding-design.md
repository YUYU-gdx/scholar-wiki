# Pipeline 变量概念 Embedding 与 MCP 语义召回设计

## 1. 背景与目标

当前 `graph_variable_neighbors(mode=semantic)` 的语义召回是轻量 hash 相似度，基于 `graph/full` 中的 `variable_definitions` 在线计算，未使用持久化向量库。

本设计目标：

1. 在 pipeline 的 agent 抽取完成并入库后，新增“变量概念 embedding 同步”步骤。
2. 复用当前 ChromaDB 同一套实现（客户端/写入方式），但使用独立变量概念索引目录。
3. MCP 侧新增“基于概念召回变量名”能力，默认 `top_k=5`，并支持入参覆盖。
4. 别名唯一数据源严格使用 `canonical_variables + variable_aliases`。
5. 提供一次性历史回填任务，补齐已存在库的数据。

## 2. 约束与确认

已由用户确认：

- 变量概念索引目录：`{workspace}/corpus/variables_concept_index/`（每 library 独立）
- 唯一粒度：`变量名 + 论文`（`paper_id + variable_name_norm`）
- 别名来源：仅 `canonical_variables + variable_aliases`
- MCP 默认召回：`top_k=5`，MCP tool 入参可覆盖
- 历史数据：必须支持一次性回填

## 3. 非目标

1. 不替换现有 `rag_search`。
2. 不移除 `graph_variable_neighbors` 的 exact 模式。
3. 不修改前端协议；仅扩展 MCP tool。
4. 不改变 `frontend/` 任何内容。

## 4. 总体架构

### 4.1 数据流（新）

1. `parse` 完成
2. `extract` 完成（agent 输出 `extract_result.json` / `raw_llm_outputs.jsonl`）
3. 结构化入库 SQLite（现有）
4. **新增：变量概念 embedding 同步到变量索引 Chroma**
5. 图谱视图构建（现有）
6. Job 完成

### 4.2 查询流（新 tool）

1. 用户 query -> MCP tool `graph_variable_concept_search`
2. Chroma 概念索引召回 top_k 文档（变量+论文粒度）
3. 从命中项取 `canonical_var_id`
4. 查 `canonical_variables + variable_aliases` 扩展别名集合
5. 回表查所有同名/别名变量对应论文
6. 聚合返回（变量组 + 论文列表 + trace）

## 5. 存储设计

### 5.1 目录与 collection

- 根目录：`{workspace}/corpus/variables_concept_index/`
- 建议 collection：`variable_concepts_v1`

### 5.2 向量文档模型

每条文档对应“一个论文中的一个变量概念”：

- `id`: `{library_id}::{paper_id}::{variable_name_norm}`
- `document`: 概念文本（优先 `definition_text`）
- `metadata`:
  - `library_id`
  - `paper_id`
  - `variable_name`
  - `variable_name_norm`
  - `canonical_var_id`
  - `updated_at`

### 5.3 幂等与更新

- 用固定 `id` upsert，重复跑仅覆盖，不重复累积。
- 若概念文本变化，以同 `id` 覆盖更新。

## 6. 数据源与规范

### 6.1 变量概念源

来源：入库后的 SQLite（`variable_definitions`），不直接依赖抽取 JSON。

### 6.2 别名唯一源

- `canonical_variables`
- `variable_aliases`

语义召回扩展逻辑只能使用上述两表，不得混入抽取中间产物 aliases。

## 7. Pipeline 改造点

目标文件：`src/kn_graph/services/pipeline_runtime.py`

### 7.1 新增步骤

在 finalize 链路、SQLite 导入成功后增加：

- `sync_variable_concept_index(workspace_path, library_id, paper_id)`

执行内容：

1. 读取本次论文 `variable_definitions`。
2. 解析 `canonical_var_id`（由 canonical/alias 体系得到）。
3. 批量写入 Chroma `variable_concepts_v1`。

### 7.2 失败策略

- 同步失败记 `warning`（`concept_index_warning`），不阻断主流程 completed。
- 在 `result.json` 增加：
  - `concept_index_result`（inserted/updated/skipped）
  - `concept_index_warning`（可空）

## 8. MCP Tool 设计

目标文件：`scripts/smj_pipeline/kn_mcp_server.py`

### 8.1 新增 tool

`graph_variable_concept_search`

入参：

- `query: string`（required）
- `top_k: integer`（optional，默认 5，范围建议 1~50）
- `library_id: string`（optional，沿用现有库作用域解析）

### 8.2 返回结构

```json
{
  "ok": true,
  "query": "...",
  "library_scope": "...",
  "top_k": 5,
  "matched_variables": [
    {
      "canonical_var_id": "...",
      "canonical_name": "...",
      "aliases": ["A", "A1"],
      "hits": [
        {"paper_id": "...", "score": 0.83, "concept_text": "..."}
      ]
    }
  ],
  "papers": [
    {
      "paper_id": "...",
      "title": "...",
      "matched_variables": ["A", "A1"]
    }
  ],
  "trace": {
    "vector_hit_count": 5,
    "expanded_alias_count": 12
  }
}
```

失败时沿用当前 MCP 错误格式：`ok=false + error_code/error_message/error_detail`。

## 9. 历史回填

新增一次性脚本（建议放 `scripts/smj_pipeline/`）：

- 扫描所有 library workspace
- 读取 SQLite `variable_definitions` 与 canonical/alias 映射
- upsert 到 `variable_concepts_v1`
- 输出每库统计：`processed/inserted/updated/skipped/errors`

脚本要求：

- 可重复执行（幂等）
- 支持单库与全量模式

## 10. 兼容性与迁移

1. 现有 `rag_search`、`graph_variable_neighbors(exact)` 保持不变。
2. `graph_variable_neighbors(semantic)` 可先保留，后续可切换为调用新概念索引或标记 deprecated。
3. 不破坏已有 pipeline API 请求体；新增行为由内部默认开启。

## 11. 观测与验收

### 11.1 验收标准

1. 新跑一次 agent pipeline 后，变量概念索引目录存在并有文档写入。
2. 同一论文重复跑，索引文档总量不异常增长（幂等）。
3. `graph_variable_concept_search` 默认 `top_k=5`，传入 `top_k` 可覆盖。
4. 命中变量 A 时，返回包含 A 与 A 别名对应的全部论文。
5. 回填脚本可对历史库完成补齐并输出统计。

### 11.2 关键日志字段

- `concept_index_result`
- `concept_index_warning`
- `vector_hit_count`
- `expanded_alias_count`

## 12. 实施顺序

1. 抽离概念索引服务模块（Chroma 读写封装）
2. Pipeline finalize 接入同步
3. MCP 新 tool 接入
4. 历史回填脚本
5. 集成测试与回归

## 13. 风险与缓解

1. 概念文本噪声：增加最小长度与空文本过滤。
2. canonical 关系不完整：trace 输出缺失映射计数，便于后续补数据。
3. 全量回填耗时：支持分库执行与断点重跑。

## 14. 结论

该方案在不破坏现有 Chroma 体系的前提下，为变量语义召回提供可持久化、可回填、可解释的索引能力，并严格遵守“别名唯一数据源”为 canonical/alias 表的约束。
