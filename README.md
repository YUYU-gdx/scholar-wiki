# kn-gragh

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
