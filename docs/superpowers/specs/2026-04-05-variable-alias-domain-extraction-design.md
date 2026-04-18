# 变量同义词与领域提取设计

## 概述

- 增加论文级领域提取，并采用来源优先级：
  1. Wiley 元数据 `topics.topicLabel`
  2. `citation_keywords`
  3. 模型回退补全
- 在关系抽取中增加变量同义词与 canonical ID。
- 增加非线性关系形态，并映射到前端三类显示：`positive|negative|nonlinear`。

## JSON 契约

顶层字段：
- `paper_domains: string[]`
- `relations: object[]`
- `variable_level_theory_grounding: object[]`
- `relation_level_theory_grounding: object[]`
- `hypotheses: object[]`
- `citations: object[]`

`relation` 必填字段：
- `source_var`
- `target_var`
- `source_aliases: string[]`
- `target_aliases: string[]`
- `source_canonical_var_id`
- `target_canonical_var_id`
- `relation_type`
- `model_tag = "main_model"`
- `relation_form = "linear|nonlinear"`
- `direction`
- `verification`
- `evidence_anchor`

正式变量名优先级：
1. 假设表述
2. 变量定义段落/章节
3. 假设检验表格表述

## 存储结构

- `paper_domains(paper_id, domain, source)`
- `canonical_variables(canonical_var_id, canonical_name)`
- `variable_aliases(canonical_var_id, alias_text, alias_norm, source, paper_id)`
- `relations(...)` 额外字段：
  - `source_canonical_var_id`
  - `target_canonical_var_id`
  - `source_alias_text`
  - `target_alias_text`
  - `relation_form`
- `alias_mentions(paper_id, relation_row_id, canonical_var_id, alias_text, alias_norm, role)`

## 前端映射

- 边显示类别计算规则：
  - `relation_form == nonlinear` -> `nonlinear`
  - 否则若方向负向 -> `negative`
  - 否则若方向正向 -> `positive`
  - 其他值回退为 `nonlinear`
- 三类颜色均可由用户配置。
