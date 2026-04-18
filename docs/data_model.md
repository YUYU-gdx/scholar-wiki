# 新版数据模型（解析-存储-API-前端一致）

## 1. 论文级字段
- `extractability_status`: `yes|no|uncertain`
- `paper_type`
- `extractability_reason`
- `extractability_evidence_section`
- `paper_domains[]`

## 2. 结构化主体
- `main_effects[]`
  - `from` / `to`
  - `effect`（`+|-|nonlinear|mixed|unclear|conditional` 等）
  - `hypothesis_label`
  - `verification`
  - `evidence_section` / `evidence_snippet`
  - `description`
- `interactions[]`
  - `inputs[]` / `output`
  - `type`（如 `moderation`）
  - `moderator`（可空）
  - `effect`
  - `hypothesis_label`
  - `verification`
  - `evidence_section` / `evidence_snippet`
  - `description`
- `context_variables[]`
- `operationalization{ variable -> { operationalized_as[] } }`

## 3. PostgreSQL 主表
- `papers`
- `paper_domains`
- `canonical_variables`
- `variable_aliases`
- `variable_definitions`
- `context_variables`
- `operationalizations`
- `direct_effects`
- `moderations`
- `moderation_targets`
- `interactions`
- `interaction_inputs`

## 4. 图谱投影约定
- 主图边来自 `main_effects`（当前物理存储复用 `direct_effects` 表）
- 调节边优先来自 `interactions(type≈moderation)` 派生；历史兼容可来自 `moderations + moderation_targets`
