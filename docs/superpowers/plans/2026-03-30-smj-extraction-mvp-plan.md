# SMJ 抽取 MVP 实施计划

> **面向执行代理：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务执行。步骤使用 `- [ ]` 复选框跟踪。

**目标：** 为本地 SMJ 全文论文构建可审计的抽取 MVP，产出变量关系、效应方向/强度、假设验证、两类理论依据、引用边，并写入 PostgreSQL + Neo4j。

**架构：** 采用混合管线：规则定位主模型证据 -> LLM 结构化标准化 -> 规则校验 -> 存储。PostgreSQL 作为事实源，Neo4j 作为图投影。跳过 OCR，跳过摘要型文档（仅摘要+参考文献）。

**技术栈：** Python 3.12、`uv`、`pytest`、`sqlite`（本地 MVP 开发桩）、PostgreSQL、Neo4j、`scripts/smj_pipeline`。

---

### 任务 1：数据契约与类型化 Schema

**文件：**
- 新建：`scripts/smj_pipeline/extraction/schemas.py`
- 新建：`tests/test_extraction_schemas.py`
- 修改：`pyproject.toml`（仅在新增依赖时）

- [ ] **步骤 1：先写失败测试**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现严格 schema 约束**
- [ ] **步骤 4：回归 schema 测试并通过**
- [ ] **步骤 5：提交代码**

### 任务 2：文档分级（A/B/C）

**文件：**
- 新建：`scripts/smj_pipeline/extraction/qualifier.py`
- 新建：`tests/test_extraction_qualifier.py`

- [ ] **步骤 1：先写失败测试（摘要型文档应为 B）**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现分级规则**
- [ ] **步骤 4：回归 qualifier 测试并通过**
- [ ] **步骤 5：提交代码**

### 任务 3：主模型证据定位

**文件：**
- 新建：`scripts/smj_pipeline/extraction/locator.py`
- 新建：`tests/test_extraction_locator.py`

- [ ] **步骤 1：先写章节/表格定位失败测试**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现最小可用定位器**
- [ ] **步骤 4：回归 locator 测试并通过**
- [ ] **步骤 5：提交代码**

### 任务 4：结构化抽取接口（混合规范化）

**文件：**
- 新建：`scripts/smj_pipeline/extraction/extractor.py`
- 新建：`scripts/smj_pipeline/extraction/prompts.py`
- 新建：`tests/test_extraction_extractor.py`

- [ ] **步骤 1：先写 parser/normalization 失败测试**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现抽取接口（关系/理论/假设/引用）**
- [ ] **步骤 4：补充离线夹具测试（不走网络）**
- [ ] **步骤 5：提交代码**

### 任务 5：校验与复核队列

**文件：**
- 新建：`scripts/smj_pipeline/extraction/validator.py`
- 新建：`scripts/smj_pipeline/extraction/review_queue.py`
- 新建：`tests/test_extraction_validator.py`

- [ ] **步骤 1：先写失败校验测试**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现校验门禁**
- [ ] **步骤 4：实现 review queue 输出（CSV/JSONL）**
- [ ] **步骤 5：回归测试并提交**

### 任务 6：存储层（PostgreSQL + Neo4j）

**文件：**
- 新建：`scripts/smj_pipeline/storage/postgres_repo.py`
- 新建：`scripts/smj_pipeline/storage/neo4j_repo.py`
- 新建：`scripts/smj_pipeline/storage/schema.sql`
- 新建：`tests/test_storage_postgres_repo.py`
- 新建：`tests/test_storage_neo4j_repo.py`

- [ ] **步骤 1：先写仓储失败测试（Neo4j 用 mock/stub）**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现 PostgreSQL 写入（事实源）**
- [ ] **步骤 4：实现 Neo4j 图投影写入**
- [ ] **步骤 5：回归测试并提交**

### 任务 7：端到端 CLI（100 篇基线）

**文件：**
- 新建：`scripts/smj_pipeline/run_extraction_mvp.py`
- 新建：`tests/test_run_extraction_mvp.py`
- 修改：`README.md`

- [ ] **步骤 1：先写失败 CLI 测试（仅 A 类计分母）**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现编排流程（分类->定位->抽取->校验->入库）**
- [ ] **步骤 4：回归测试通过**
- [ ] **步骤 5：提交代码**

### 任务 8：指标与验收报告

**文件：**
- 新建：`scripts/smj_pipeline/evaluation/metrics.py`
- 新建：`scripts/smj_pipeline/evaluation/report_template.md`
- 新建：`tests/test_evaluation_metrics.py`
- 新建：`outputs/smj_extraction_mvp/`（运行产物目录）

- [ ] **步骤 1：先写失败指标测试**
- [ ] **步骤 2：执行测试并确认失败**
- [ ] **步骤 3：实现验收指标计算**
- [ ] **步骤 4：基线跑批并输出报告**
- [ ] **步骤 5：提交代码**

## 全局验收清单（收尾前）

- [ ] 单测总回归：`uv run pytest -q tests`
- [ ] 基线端到端：`uv run python scripts/smj_pipeline/run_extraction_mvp.py --sample-size 100`
- [ ] 确认 Class B 被跳过且不计入分母
- [ ] 确认所有 relation 均有 evidence anchor
- [ ] 确认 PostgreSQL 与 Neo4j 投影计数一致
- [ ] 验收报告输出到 `outputs/smj_extraction_mvp/acceptance_report.md`
