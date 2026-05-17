# Agent 工作指南（Workspace 通用版）

## 1. 工具总览（全量）

当前 MCP 服务 `kn_graph_tools` 暴露 3 个工具：
1. `rag_search`
2. `graph_variable_neighbors`
3. `graph_variable_concept_search`

### 1.1 rag_search
用途：
- 在文献库中做混合检索（向量+关键词），返回句子/段落证据。
- 用于回答问题、验证结论、补充证据。

什么时候用：
- 任何需要“证据文本”的任务都应优先使用。
- 结论、对比、冲突判断必须先有该工具证据。

输入参数：
- `query` (string, 必填)：检索问题/语句。
- `vector_weight` (number, 可选, 0~1)：向量权重。
- `top_k` (integer, 可选, 3~20)：返回条数。
- `library_id` (string, 可选)：指定文献库；不传时按当前 workspace 自动推断。

输出关键字段：
- `ok`：是否成功。
- `query`：实际检索词。
- `library_scope`：检索作用域（单库或 all）。
- `weights.vector / weights.keyword`：归一化后的检索权重。
- `top_k`：实际使用的 top_k。
- `hits[]`：证据列表，每项包含：
  - `score`：命中分数。
  - `sentence_text`：句子证据。
  - `paragraph_text`：段落证据。
  - `paper_path_abs`：证据对应论文绝对路径。
  - `paper_id`：论文 ID。
  - `library_id`：所属文献库。
- `truncated`：是否因返回过长被截断。
- `truncate_reason`：截断原因。

失败字段：
- `error_code` / `error_message` / `error_detail`。

---

### 1.2 graph_variable_neighbors
用途：
- 查变量邻域关系（上游/下游），用于变量对齐、机制辅助判断。
- 只对真实 KG 节点有效；`graph_variable_concept_search` 返回的 `in_kg=false` 候选没有图谱邻居。

什么时候用：
- 当问题涉及“变量关系、因果方向、邻近变量”时使用。
- 仅在已知变量为 KG 节点时使用；优先使用 `graph_variable_concept_search` 检查 `in_kg` / `kg_node_id`。
- 不能替代段落证据；必须与 `rag_search` 联合使用。

输入参数：
- `variable_name` (string, 必填)：变量名。
- `mode` (string, 必填)：`exact` 或 `semantic`。
- `vector_weight` (number, 可选, 0~1)。
- `top_k` (integer, 可选, 3~20)。
- `library_id` (string, 可选)。

输出关键字段：
- `ok`。
- `library_scope`。
- `query_variable`：输入变量。
- `query_variable_path_abs`：匹配变量的主要论文路径（绝对路径）。
- `match_mode`：`exact` / `semantic`。
- `weights`。
- `matched_variable`：最终匹配变量：
  - `variable_id`、`variable_name`、`library_id`、`score`、`concept_text`。
- `candidates[]`：候选变量：
  - `variable_id`、`variable_name`、`library_id`、`score`、`concept_text`、`relation_to_current`。
- `upstream[]`：上游变量（指向当前变量）。
- `downstream[]`：下游变量（由当前变量指向）。
- `todos[]`：待处理提示（如语义模式下概念缺失）。
- `truncated` / `truncate_reason`。

---

### 1.3 graph_variable_concept_search
用途：
- 按“概念文本”检索变量候选，返回变量、别名、论文以及可用的因果邻域。
- 结果可能是 definition-only 候选，不保证存在 KG 节点；必须检查 `in_kg` 与 `kg_node_id`。

什么时候用：
- 当用户给的是概念描述，而不是明确变量名。
- 需要跨论文聚合同类变量时。

输入参数：
- `query` (string, 必填)：概念查询文本。
- `top_k` (integer, 可选, 3~20)。
- `library_id` (string, 可选)。

输出关键字段：
- `ok`、`query`、`top_k`、`library_scope`。
- `matched_variables[]`：匹配变量，每项包含：
  - `id`、`score`、`library_id`、`paper_id`。
  - `variable_name`、`canonical_var_id`。
  - `kg_node_id`：真实 KG 节点 ID；为空表示没有对齐到 KG 节点。
  - `in_kg`：是否为真实 KG 节点；只有 `true` 才适合继续调用 `graph_variable_neighbors`。
  - `aliases[]`：别名列表。
  - `concept_text`：概念文本。
  - `cause_variables[]`：上游变量集合。
  - `effect_variables[]`：下游变量集合。
- `papers[]`：涉及论文列表（`library_id` + `paper_id`）。
- `trace.libraries[]`：每个库的查询跟踪信息（workspace、db_path、hit_count 等）。
- `truncated` / `truncate_reason`。

---

## 2. 工具使用策略（强约束）

- 证据优先顺序：`rag_search` > 图谱邻域工具。
- 图谱工具用于“变量定位/关系辅助”，不作为唯一证据来源。
- `graph_variable_concept_search` 的 `in_kg=false` 只表示概念候选，不表示有图谱邻居。
- 只对 `in_kg=true` 或已知 `kg_node_id` 的变量调用 `graph_variable_neighbors`。
- 如 `truncated=true`，回答中必须说明“结果被截断”。
- 常见错误处理：
  - `no_hits`：改写 query（加上下文定义、方法、场景词）后重试。
  - `variable_not_found`：先用 `graph_variable_concept_search` 检查候选；若候选 `in_kg=false`，不要再强行调用 neighbors。
  - `library_not_found` / `workspace_path_missing`：先确认当前 workspace 绑定库。
  - `backend_timeout`：缩短 query、降低 top_k、分步检索。

---

## 3. Workspace 层级与目录解释（`{data_dir}/libraries/workspaces/`）

以下只解释 `workspaces` 目录树本身。你可以把它理解成“根 workspace + 多个库 workspace”的并存结构：

```text
{data_dir}/libraries/workspaces/
├─ .claude/
│  └─ skills/
├─ .agents/
│  └─ skills/
├─ CLAUDE.md
├─ AGENTS.md
├─ {library_id_A}/
│  ├─ .claude/
│  │  └─ skills/
│  ├─ .agents/
│  │  └─ skills/
│  ├─ CLAUDE.md
│  ├─ AGENTS.md
│  ├─ sources/
│  │  ├─ pdf/
│  │  ├─ markdown/
│  │  ├─ text/
│  │  └─ html/
│  ├─ imports/
│  │  └─ jobs/
│  ├─ corpus/
│  │  ├─ papers/
│  │  ├─ md_library/
│  │  └─ index/
│  ├─ chromadb/
│  ├─ kn_gragh.db
│  └─ graph_views.json
└─ {library_id_B}/
   └─ ...
```

逐层说明如下：

- `{data_dir}/libraries/workspaces/`：
  - 所有 Agent 工作空间的根目录。
  - 顶层本身是 chat_root 工作区，同时也是所有库工作区的父目录。

- 顶层 `.claude/skills/`、`.agents/skills/`：
  - 根 workspace 的技能发现目录。
  - 用于问答场景下自动发现可用 skill。

- 顶层 `CLAUDE.md`、`AGENTS.md`：
  - 根 workspace 的 Agent 说明入口文件。
  - Agent 在该层 cwd 运行时会读取这一层文档约束。

- `{library_id}/`：
  - 单个文献库的独立 workspace（pipeline_library）。
  - 该目录内数据、索引、抽取产物与 Agent 运行上下文按库隔离。

- `{library_id}/.claude/skills/`、`{library_id}/.agents/skills/`：
  - 库级 workspace 的技能发现目录。
  - 用于抽取链路等库内任务自动发现 skill。

- `{library_id}/CLAUDE.md`、`{library_id}/AGENTS.md`：
  - 库级 workspace 的说明入口文件。
  - Agent 在库目录运行时会按这一层规则执行。

- `{library_id}/sources/`：
  - 原始输入文件归档目录（按类型分层）。
  - 常见子目录：`pdf/`、`markdown/`、`text/`、`html/`。

- `{library_id}/imports/jobs/`：
  - Pipeline 任务目录。
  - 每个 `job_id` 子目录包含该次任务的输入、解析、抽取中间产物与结果。

- `{library_id}/corpus/`：
  - 文献物化语料目录。
  - `papers/`：按 `paper_key` 管理单篇论文的 source/derived/meta。
  - `md_library/`：Reader 侧可直接使用的 Markdown 组织目录。
  - `index/`：语料索引（如 `papers.ndjson`）。

- `{library_id}/chromadb/`：
  - 该库的向量索引持久化目录（按库隔离）。

- `{library_id}/kn_gragh.db`：
  - 该库的本地数据库文件（用于检索/映射等能力依赖的数据）。

- `{library_id}/graph_views.json`：
  - 图谱视图数据文件，供图谱与相关查询能力读取。

作用域约定：
- cwd 在 `workspaces/` 顶层：默认面向根 workspace（可跨库）。
- cwd 在 `workspaces/{library_id}/`：默认绑定该库 workspace。
- 需要强制单库时，显式传 `library_id`，并检查返回 `library_scope`。

---

## 4. 执行建议（按任务类型）

- 文献问答：
  1. `rag_search` 取证据。
  2. 如涉及变量机制，再补 `graph_variable_neighbors`。
  3. 输出时附证据来源与不确定性。

- 文献抽取：
  1. 先从正文抽取结构化字段。
  2. 用图谱工具做变量对齐与别名核对。
  3. 用 `rag_search` 回查关键关系证据。

- 概念映射：
  1. `graph_variable_concept_search` 找候选。
  2. 检查 `in_kg` / `kg_node_id`；只有 `in_kg=true` 才补 `graph_variable_neighbors`。
  3. 再用 `rag_search` 逐条验证语义一致性。

---

## 5. 基本边界

- 不要改动与当前任务无关的文件。
- 不要将推测写成事实。
- 关键结论必须可追溯到工具输出字段。
