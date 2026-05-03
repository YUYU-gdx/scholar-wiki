# 数据模型规约（抽取 -> 存储 -> 投影 -> API）

## 1. 分层模型总览
- L1 抽取层：模型输出 JSON（由 `prompt/extraction_system_prompt.md` 约束，`extraction/extractor.py` 解析与校验）。
- L2 存储层：PostgreSQL 标准化表（`scripts/smj_pipeline/storage/schema_postgres.sql`）。
- L3 产物层：前端 artifact（`export_frontend_artifact.py` 输出）与 graph views（`build_graph_views.py` 输出）。
- L4 服务层：`kn_graph serve` / `serve_graph_api.py` 直接读取 graph views 对外提供接口。

## 2. L1 抽取层（模型返回契约）

### 2.1 必填顶层字段
- `extractability_status`：`yes|no|uncertain`
- `paper_type`
- `extractability_reason`
- `extractability_evidence_section`
- `direct_effects`（数组）

### 2.2 可选顶层字段
- `variable_definitions`
- `moderations`
- `interactions`
- `paper_domains`（由 HTML 元数据填充，不由 LLM 产出）

### 2.3 关键子结构
- `direct_effects[]`
  - `source`、`target`、`effect_form`、`theory_name`、`evidence_text`、`verification`
- `moderations[]`
  - `moderator`、`source`、`target`、`effect_form`、`theory_name`、`evidence_text`、`verification`
- `interactions[]`
  - `inputs[]`（至少 2 个）、`output`、`effect_form`、`theory_name`、`evidence_text`、`verification`
- `variable_definitions[]`
  - `variable_name`、`definition`、`measurement`、`aliases[]`

### 2.4 枚举约束（解析器校验）
- `effect_form`：`positive|negative|nonlinear|unclear`
- `verification`：`supported|not_supported|mixed|unclear`
- `extractability_status`：`yes|no|uncertain`

## 3. L2 存储层（PostgreSQL 表）

### 3.1 论文主表
- `papers`
  - 主键：`paper_id`
  - 元数据：`doi`、`offline_html_path`、`article_url`、`publication_date`、`online_date`、`publication_year`、`paper_citation_count`、`metadata_source`
  - 分流字段：`extractability_status`、`paper_type`、`extractability_reason`、`extractability_evidence_section`

### 3.2 论文扩展表
- `paper_domains(paper_id, domain, source)`
- `variable_definitions(paper_id, variable_name, aliases_json, definition_text, measurement_text)`

### 3.3 变量规范化表
- `canonical_variables(canonical_var_id, canonical_name)`
- `variable_aliases(canonical_var_id, alias_text, alias_norm, source, paper_id)`

### 3.4 关系表
- `direct_effects`
  - `paper_id`
  - `source_var` / `target_var`
  - `source_canonical_var_id` / `target_canonical_var_id`
  - `source_alias_json` / `target_alias_json`
  - `effect_form` / `theory_name`
  - `verification` / `evidence_text`
- `moderations`
  - `paper_id`
  - `moderator_var` / `moderator_canonical_var_id` / `moderator_alias_json`
  - `source_var` / `target_var` / `source_canonical_var_id` / `target_canonical_var_id`
  - `effect_form` / `theory_name`
  - `verification` / `evidence_text`
- `interactions`
  - `paper_id`
  - `output_var` / `output_canonical_var_id`
  - `effect_form` / `theory_name`
  - `verification` / `evidence_text`
- `interaction_inputs`
  - `interaction_id`
  - `input_var` / `input_canonical_var_id` / `input_order`

### 3.5 主键与索引
- 主要索引：`papers.publication_year`、`direct_effects.paper_id`、`direct_effects(source_canonical_var_id,target_canonical_var_id)`、`moderations.paper_id`、`interactions.paper_id`。
- 别名唯一约束：`variable_aliases(canonical_var_id, alias_norm)`。

## 4. L3 产物层

### 4.1 Frontend artifact (`frontend_artifact.json`)
- 顶层：`meta`、`nodes[]`、`edges[]`、`moderation_links[]`、`interaction_links[]`、`papers[]`。
- `nodes[]`
  - 变量节点，`id` 默认 `var::<变量名>`，含 `label/name/canonical_var_id`、`aliases/alias_count`、`first_year`。
- `edges[]`
  - 关键字段：`source`、`target`、`paper_id`、`doi`、`effect_form`、`theory_name`、`verification`、`evidence_text`、`paper_year`、`display_effect_class`。
- `moderation_links[]`
  - 关键字段：`moderator_var/moderator_node_id`、`moderated_relation{source,target}`、`effect_form`、`theory_name`、`verification`、`evidence_text`。
- `interaction_links[]`
  - 关键字段：`inputs/input_node_ids`、`output/output_node_id`、`effect_form`、`theory_name`、`verification`、`evidence_text`。
- `papers[]`
  - API 论文详情来源，包含分流字段、变量定义、直接效应、交互效应、论文领域。

### 4.2 Graph views (`graph_views.json`)
- 在 artifact 基础上增加：
  - `nodes`（由数组转 map，key 为 `node_id`）
  - `edge_index_by_node`
  - `overview{node_ids, edge_indexes}`
  - `paper_map`（以 `paper_id` 和 `doi` 双 key 索引）
  - 节点侧统计：`paper_profile`、`paper_count_mentions`、`dominant_paper_id`、`paper_entropy`

## 5. L4 API 层字段映射
- `/paper/{id}` 直接返回 `paper_map` 对象。
- `/variable/{id}`：
  - `concepts` 来自 `variable_definitions` 过滤匹配该变量名。
  - `measurement_methods` 来自 `variable_definitions[].measurement`。
  - `relations` 来自 `edges/moderation_links/interaction_links` 聚合。
- `/graph/search`：
  - 变量检索索引来自节点 + 关系邻接摘要。
  - 论文检索索引来自 `papers.direct_effects/interactions/paper_domains`。
