# 可复用流程：批量提取 + 自动评测

## 一键流程（推荐）

```powershell
uv run python scripts/smj_pipeline/run_latest_n_reusable_workflow.py --n 30 --model glm-4-plus --judge-model glm-4-plus
```

该命令会自动执行：

1. 提交最新 `N` 篇论文到 batch 提取。
2. 轮询等待 batch 完成。
3. 物化结果并生成前端产物（`frontend_artifact.json`、`graph_views.json`）。
4. 逐篇 LLM 评测并输出报告。

## Ground Truth 模式

如果你有标注好的 GT（与 `## xxx_offline.html` 结构一致）：

```powershell
uv run python scripts/smj_pipeline/run_latest_n_reusable_workflow.py --n 30 --model glm-4-plus --judge-model glm-4-plus --gt-markdown "outputs/casepack_moderation_10/ground truth.batch.md"
```

## 仅准备不提交（调试）

```powershell
uv run python scripts/smj_pipeline/run_latest_n_reusable_workflow.py --n 30 --skip-submit
```

## 评测输出位置

默认在对应 run 目录下：

- `outputs/runs/<run_id>/evaluation_llm/<timestamp>/judge_per_paper.jsonl`
- `outputs/runs/<run_id>/evaluation_llm/<timestamp>/judge_summary.md`
- `outputs/runs/<run_id>/evaluation_llm/<timestamp>/raw/`
- `outputs/runs/<run_id>/evaluation_llm/<timestamp>/clean_html_no_refs/`

## 当前评测口径

- 有 GT：按 `ground truth + batch + 原文` 评测。
- 无 GT：按 `batch + 原文` 做逻辑一致性评测（同义表述视为可接受）。

## 提示词版本管理

- 抽取提示词以生产模板为准：`prompt/extraction_system_prompt.md`。
- `prompts.py` 会在运行时加载该模板，因此 `run_extraction_mvp.py` 与 `run_full_batch_inference.py` 共用同一提示词版本。
- `outputs/` 目录中的提示词文件仅用于实验与对照，不作为线上默认来源。
