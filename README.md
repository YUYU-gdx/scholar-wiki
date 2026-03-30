# kn-gragh

## SMJ extraction MVP runner

Run the Task 7 orchestrator against a local JSONL manifest whose rows include at least `paper_id` and `html`:

```bash
uv run python scripts/smj_pipeline/run_extraction_mvp.py --input-manifest path/to/manifest.jsonl --sample-size 100
```

The runner classifies each document, skips class `B`, and stops after collecting the requested number of class `A` documents. The printed summary includes `seen`, `class_a_used`, `class_b_skipped`, `class_c_skipped`, and `denominator_used`.
