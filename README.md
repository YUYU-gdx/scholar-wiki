# kn-gragh

## API Docs

- Graph API 文档: `docs/api.md`
- 抽取契约设计: `docs/superpowers/specs/2026-04-05-variable-alias-domain-extraction-design.md`

## SMJ Graph Desktop Launcher

### Start

```bash
uv run python scripts/smj_pipeline/app_launcher.py
```

### Features

- Button 1: `导入文件并解析`  
  Select a frontend artifact JSON and build `outputs/smj_batch_full/graph_views.json`.
- Button 2: `导入 PostgreSQL`  
  Input DSN, export to frontend artifact, then build graph views.
- Button 3: `打开展示`  
  Start local graph service and open browser automatically.

### Visualization

- Full graph load on startup with loading spinner and stage text.
- Clear edge arrows (not particle flow).
- Positive/negative effects use different colors.
- User-configurable colors for node, positive edge, negative edge, and background.

## SMJ Extraction MVP Runner

The runner supports local JSONL rows with either:
- inline `html`
- or file paths: `offline_html_path` / `raw_html_path` / `html_path` / `full_html_path`

### Run with Zhipu model

```bash
set ZHIPU_API_KEY=your_key_here
uv run python scripts/smj_pipeline/run_extraction_mvp.py --input-manifest path/to/manifest.jsonl --sample-size 100 --llm-provider zhipu --llm-model glm-4.5-flash
```

### Optional outputs

```bash
uv run python scripts/smj_pipeline/run_extraction_mvp.py ^
  --input-manifest path/to/manifest.jsonl ^
  --sample-size 100 ^
  --review-queue-jsonl outputs/smj_extraction_mvp/review_queue.jsonl ^
  --report-output outputs/smj_extraction_mvp/acceptance_report.md
```

### Behavior

- Class A documents are processed.
- Class B documents (`abstract + references` only) are skipped.
- Class B does not count toward the class-A denominator.
- The pipeline executes: classify -> locate -> extract -> validate -> (optional) storage.
