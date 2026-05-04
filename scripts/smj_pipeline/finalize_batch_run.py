from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from run_registry import DEFAULT_RUNS_ROOT, run_dir, set_active, write_json_atomic


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Finalize one submitted run: materialize -> export -> build -> optional activate.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    p.add_argument("--batch-id", default="")
    p.add_argument("--api-key-env", default="ZHIPU_API_KEY")
    p.add_argument("--db-path", type=Path, help="Path to SQLite database (required for graph build).")
    p.add_argument("--activate", action="store_true")
    return p.parse_args()


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def _discover_batch_id(submit_summary_path: Path) -> str:
    payload = json.loads(submit_summary_path.read_text(encoding="utf-8"))
    if isinstance(payload.get("batches"), list) and payload["batches"]:
        return str((payload["batches"][0] or {}).get("batch_id", "")).strip()
    batch = payload.get("batch")
    if isinstance(batch, dict):
        return str(batch.get("id", "")).strip()
    return ""


def main() -> None:
    args = parse_args()
    rdir = run_dir(args.run_id, args.runs_root)
    if not rdir.exists():
        raise RuntimeError(f"run directory not found: {rdir}")
    submit_summary_path = rdir / "submit_summary.json"
    if not submit_summary_path.exists():
        raise RuntimeError(f"submit summary not found: {submit_summary_path}")

    batch_id = str(args.batch_id).strip() or _discover_batch_id(submit_summary_path)
    if not batch_id:
        raise RuntimeError("unable to determine batch_id")

    submitted_request_jsonl = rdir / "requests" / "batch_requests_part_001.jsonl"
    if not submitted_request_jsonl.exists():
        raise RuntimeError(f"submitted request shard not found: {submitted_request_jsonl}")

    _run(
        [
            "uv",
            "run",
            "python",
            "scripts/smj_pipeline/materialize_batch_results.py",
            "--batch-id",
            batch_id,
            "--api-key-env",
            str(args.api_key_env),
            "--submitted-request-jsonl",
            str(submitted_request_jsonl),
            "--original-request-jsonl",
            str(submitted_request_jsonl),
            "--out-dir",
            str(rdir),
        ],
        Path.cwd(),
    )

    # Import extraction results into SQLite (single source of truth for paper data)
    raw_output_jsonl = rdir / "extract" / "raw_llm_outputs.jsonl"
    if raw_output_jsonl.exists() and args.db_path:
        db_path = Path(args.db_path).resolve()
        _run(
            [
                "uv", "run", "python",
                "scripts/smj_pipeline/import_raw_outputs_to_sqlite.py",
                "--db-path", str(db_path),
                "--raw-output-jsonl", str(raw_output_jsonl),
            ],
            Path.cwd(),
        )

    # Build graph views from SQLite (single source of truth)
    views_out = rdir / "graph_views.json"
    if args.db_path:
        db_path = Path(args.db_path).resolve()
        _run(
            [
                "uv", "run", "python",
                "scripts/smj_pipeline/build_graph_views.py",
                "--db-path", str(db_path),
                "--output-json", str(views_out),
            ],
            Path.cwd(),
        )
    else:
        views_out.write_text("{}", encoding="utf-8")

    meta_path = rdir / "run_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            meta = {}
    meta["status"] = "ready"
    meta["batch_id"] = batch_id
    meta["artifact_json"] = ""
    meta["graph_views"] = str(views_out)
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(meta_path, meta)

    active_info = {}
    if args.activate:
        ap = set_active(args.run_id, views_out, args.runs_root)
        active_info = {"active_file": str(ap), "active_run_id": args.run_id}

    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "status": "ready",
                "batch_id": batch_id,
                "artifact_json": "",
                "graph_views": str(views_out),
                **active_info,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
