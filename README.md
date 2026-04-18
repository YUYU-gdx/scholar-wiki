# kn-gragh

## 文档入口

- Graph API 文档：`docs/api.md`
- 抽取契约设计：`docs/superpowers/specs/2026-04-05-variable-alias-domain-extraction-design.md`
- SMJ 抽取设计（历史版本）：`docs/superpowers/specs/2026-03-29-smj-extraction-design.md`
- SMJ 抽取实施计划（历史版本）：`docs/superpowers/plans/2026-03-30-smj-extraction-mvp-plan.md`

## 生产提示词来源

- 当前生产抽取提示词文件：`prompt/extraction_system_prompt.md`
- 真实接口通过 `scripts/smj_pipeline/extraction/prompts.py` 动态加载该文件。
- `prompt/` 目录是全项目唯一提示词加载源；若需调整线上抽取行为，请修改该目录下模板。

## SMJ 图谱桌面启动器

### 启动

```bash
uv run python scripts/smj_pipeline/app_launcher.py
```

### 功能

- 按钮 1：`导入文件并解析`
  选择前端 artifact JSON，构建 `outputs/smj_batch_full/graph_views.json`。
- 按钮 2：`导入 PostgreSQL`
  输入 DSN，导出前端 artifact，再构建 graph views。
- 按钮 3：`打开展示`
  自动启动本地图谱服务并打开浏览器。

## 从模型原始输出重建数据（推荐）

当你已经有 `raw_llm_outputs*.jsonl`，推荐走这条链路：

1. 导入 Postgres（唯一事实源）  
2. 从 Postgres 导出前端 artifact  
3. 构建 graph views 并启动服务

```bash
uv run python scripts/smj_pipeline/import_raw_outputs_to_postgres.py ^
  --dsn postgresql://user:pass@127.0.0.1:5432/kn_graph ^
  --raw-output-jsonl outputs/your_run/raw_llm_outputs.jsonl ^
  --apply-schema
```

```bash
uv run python scripts/smj_pipeline/export_frontend_artifact_from_postgres.py ^
  --dsn postgresql://user:pass@127.0.0.1:5432/kn_graph ^
  --output-json outputs/smj_batch_full/frontend_artifact_from_postgres.json
```

## 供应链数据源锁定（当前默认）

- 当前默认运行指针：`outputs/runs/active.json`
- 已锁定数据源目录：`outputs/smj_supply_chain_batch/supply_chain_merged_20260414_113031`
- 入口脚本默认拒绝非供应链目录输入；如确需覆盖，显式加 `--allow-non-supply-chain`。

### 可视化

- 启动即全量加载，带加载转圈与阶段提示文案。
- 边使用清晰箭头（不再依赖小球流动）。
- 边按三类效果着色：正向 / 负向 / 非线性。
- 节点色、正向色、负向色、非线性色、背景色可由用户配置。

## SMJ 抽取 MVP 运行器

运行器支持本地 JSONL 输入，单行记录可包含：
- 内联 `html`
- 或路径字段：`offline_html_path` / `raw_html_path` / `html_path` / `full_html_path`

### 使用智谱模型运行

```bash
set ZHIPU_API_KEY=your_key_here
uv run python scripts/smj_pipeline/run_extraction_mvp.py --input-manifest path/to/manifest.jsonl --sample-size 100 --llm-provider zhipu --llm-model glm-4.5-flash
```

### 使用 NVIDIA 接口运行（GLM 4.7）

```bash
set NVIDIA_API_KEY=your_nvapi_key_here
uv run python scripts/smj_pipeline/run_extraction_mvp.py --input-manifest path/to/manifest.jsonl --sample-size 100 --llm-provider nvidia --llm-model z-ai/glm4.7 --llm-api-key-env NVIDIA_API_KEY --llm-base-url https://integrate.api.nvidia.com/v1/chat/completions
```

### 可选输出

```bash
uv run python scripts/smj_pipeline/run_extraction_mvp.py ^
  --input-manifest path/to/manifest.jsonl ^
  --sample-size 100 ^
  --review-queue-jsonl outputs/smj_extraction_mvp/review_queue.jsonl ^
  --report-output outputs/smj_extraction_mvp/acceptance_report.md
```

### 行为说明

- 仅处理 Class A 文档。
- Class B 文档（仅摘要 + 参考文献）会被跳过。
- Class B 不计入 Class A 分母。
- 管线顺序：分类 -> 定位 -> 抽取 -> 校验 -> （可选）入库。

## 新版解析模型
当前生产链路统一使用 casepack 对齐字段：`extractability_status`、`main_effects`、`interactions`、`context_variables`、`operationalization`、`non_regression_relations`。  
数据库物理层仍保留 `direct_effects` 等历史表名用于兼容，但逻辑模型以 `main_effects` 为准。
详细字段见 docs/data_model.md。

