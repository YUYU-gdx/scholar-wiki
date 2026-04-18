# SMJ 抽取与知识库设计（子项目 2）

日期：2026-03-29  
状态：草稿（待用户评审）

## 1. 目标与范围

本设计定义本地论文的抽取与知识库层，重点覆盖：变量关系、理论依据、假设验证、引用关系，为后续 3D 图谱可视化提供结构化数据。

范围内：
- 仅处理本地论文（当前主要是 SMJ）
- 当前阶段不做 OCR
- 仅处理可判定为全文的文档
- 双存储：PostgreSQL（事实源）+ Neo4j（图投影）

范围外：
- OCR 管线
- 控制变量抽取
- 稳健性/附录模型抽取
- 句级引用意图分类

## 2. 输入分级

### 2.1 文档类别
- Class A（全文）：可进入正式抽取
- Class B（仅摘要 + 参考文献）：直接跳过
- Class C（结构损坏或关键字段缺失）：进入修复队列

### 2.2 Class A 判定
必须同时满足：
1. 至少包含 `Hypotheses` 或 `Results` 主体块之一
2. 至少包含一处主模型结果表或等价统计段落

确认规则：
- Class B 不计入 100 篇样本分母
- 仅 Class A 进入抽取

## 3. 抽取目标

### 3.1 变量角色与关系类型
变量角色：
- 自变量
- 因变量
- 调节变量
- 中介变量

不抽取：
- 控制变量

关系类型：
- direct
- moderation
- mediation

### 3.2 关系必备字段
- 方向：`positive | negative | u_shape | inverted_u | non_significant`
- 效应强度：仅主模型统计值（例如 beta、OR/HR、r、CI、p）
- 假设验证：`supported | partially_supported | not_supported`
- 证据锚点：文本片段/表格编号/章节标记

### 3.3 两类理论依据
- 变量级理论依据（变量为何成立/如何定义）
- 关系级理论依据（为何 A->B 应成立）

## 4. 引用抽取

阶段 1 输出：
- `Paper A -> Paper B (cited)` 边
- 引用位置标签：`background | hypothesis | discussion`

阶段 1 暂不包含：
- 句级引用动机分类

## 5. 架构（推荐：混合抽取）

采用“规则定位 + LLM 结构化 + 规则校验”的混合流程。

流程：
1. 文档标准化解析（HTML/PDF 文本层）
2. 章节与主模型证据定位（Hypotheses/Results/Table）
3. 候选关系抽取（变量/假设/统计）
4. LLM 结构化归一（角色、方向、强度、验证、两类理论）
5. 规则校验（一致性、格式、主模型约束）
6. 写入 PostgreSQL，并将图查询所需字段投影到 Neo4j
7. 失败项进入 review queue

## 6. 数据模型（MVP）

### 6.1 PostgreSQL（事实源）
核心表：
- `paper`
- `variable`
- `hypothesis`
- `relation`
- `variable_theory`
- `relation_theory`
- `evidence`
- `citation_edge`

约束：
- 每条正式 `relation` 必须关联至少一条 `evidence`
- `model_tag` 必须为 `main_model`

### 6.2 Neo4j（查询投影）
核心节点：
- `Paper`
- `Variable`
- `Theory`
- `Hypothesis`

核心关系：
- `(:Variable)-[:AFFECTS {type,direction,strength,...}]->(:Variable)`
- `(:Variable)-[:GROUNDED_BY]->(:Theory)`
- `(:RelationProxy)-[:JUSTIFIED_BY]->(:Theory)`
- `(:Paper)-[:CITES {section_tag}]->(:Paper)`

说明：
- Neo4j 只保留图查询必要字段
- 详细证据留在 PostgreSQL，通过 ID 关联

## 7. 校验与失败处理

校验项：
- 假设标签一致性（H1/H2a 与结论是否匹配）
- 方向与显著性一致性
- 强度字段格式有效性
- 主模型约束（排除 robustness/appendix）

失败分类：
- `parse_failed`
- `main_model_uncertain`
- `hypothesis_mismatch`
- `effect_conflict`
- `evidence_missing`

策略：
- 失败项进入 review queue
- 保留候选值与证据，供人工修正

## 8. MVP 验收

样本策略：
- 仅 Class A
- 100 篇基线（Class B 不计入分母）

验收指标：
- Class A 关系抽取覆盖率
- 字段完整性（方向/强度/验证/证据）
- 假设验证准确率
- 两类理论依据可追溯性
- 引用边可定位率

## 9. 风险与缓解

风险：
- 老论文写作风格差异大
- 表格结构噪声导致统计值错配
- 同名变量在不同论文语义漂移

缓解：
- 先做 100 篇高精度基线，再迭代规则
- 维护变量归一化词典并引入复核闭环
- 优先人工复核高影响关系

## 10. 下一步

用户确认本设计后：
- 进入实施计划阶段（模块边界、数据模式、样本跑批与评估方案）
