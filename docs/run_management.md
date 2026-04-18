# Run Management (Batch Experiments)

This project now supports isolated run directories and an active pointer for frontend/API data switching.

## 1) Create and submit latest N run (example: 30)

```powershell
uv run python scripts/smj_pipeline/run_latest_n_batch.py --n 30
```

Outputs are written to:

- `outputs/runs/<run_id>/manifest_input.jsonl`
- `outputs/runs/<run_id>/submit_summary.json`
- `outputs/runs/<run_id>/run_meta.json`

## 2) Finalize one submitted run

After batch status becomes completed, materialize and build frontend views:

```powershell
uv run python scripts/smj_pipeline/finalize_batch_run.py --run-id <run_id>
```

This creates:

- `outputs/runs/<run_id>/frontend_artifact.json`
- `outputs/runs/<run_id>/graph_views.json`
- `outputs/runs/<run_id>/run_meta.json` (`status=ready`)

Activate immediately:

```powershell
uv run python scripts/smj_pipeline/finalize_batch_run.py --run-id <run_id> --activate
```

## 3) Activate / rollback

Set active run manually:

```powershell
uv run python scripts/smj_pipeline/activate_run.py --run-id <run_id>
```

List all runs and current active pointer:

```powershell
uv run python scripts/smj_pipeline/list_runs.py
```

## 4) Start API with active pointer

When `--views-json` is omitted, API reads `outputs/runs/active.json` automatically:

```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --port 8014
```

Override explicitly:

```powershell
uv run python scripts/smj_pipeline/serve_graph_api.py --views-json outputs/runs/<run_id>/graph_views.json --port 8014
```

## 5) Supply/Chain 专题筛选并提交 Batch

先从全量成功清单里按词典筛出供应链相关论文（仅匹配标题+摘要+关键词）：

```powershell
uv run python scripts/smj_pipeline/filter_manifest_supply_chain.py `
  --input-manifest outputs/smj_extraction_mvp/manifest_from_success_nobom.jsonl `
  --lexicon prompt/supply_chain_lexicon.md `
  --output-dir outputs/smj_supply_chain_batch
```

脚本会创建 `outputs/smj_supply_chain_batch/<run_id>/`，主要包含：

- `manifest_input.jsonl`
- `filter_report.json`
- `hits_preview.csv`

然后提交 `glm-4-plus`，并且仅跑 Class A：

```powershell
uv run python scripts/smj_pipeline/run_full_batch_inference.py `
  --input-manifest outputs/smj_supply_chain_batch/<run_id>/manifest_input.jsonl `
  --output-dir outputs/smj_supply_chain_batch/<run_id> `
  --model glm-4-plus `
  --class-a-only `
  --submit
```
