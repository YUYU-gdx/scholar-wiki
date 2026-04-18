from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from run_registry import DEFAULT_RUNS_ROOT, ensure_runs_root, run_dir, utc_run_id, write_json_atomic


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create one isolated run and submit latest N SMJ papers to Batch API.")
    p.add_argument("--source-csv", type=Path, default=Path("outputs/smj_all_run/manifest.csv"))
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    p.add_argument("--run-id", default="")
    p.add_argument("--model", default="glm-4.5")
    p.add_argument("--no-submit", action="store_true", help="Only prepare request shards, do not submit batch")
    p.add_argument("--api-key-env", default="ZHIPU_API_KEY")
    return p.parse_args()


def _parse_date(text: str) -> tuple[int, int, int]:
    t = str(text or "").strip()
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        try:
            return (int(t[:4]), int(t[5:7]), int(t[8:10]))
        except ValueError:
            return (0, 0, 0)
    if len(t) >= 4 and t[:4].isdigit():
        return (int(t[:4]), 1, 1)
    return (0, 0, 0)


def _load_latest_rows(source_csv: Path, n: int) -> list[dict[str, Any]]:
    if not source_csv.exists():
        raise RuntimeError(f"source csv not found: {source_csv}")
    rows: list[dict[str, Any]] = []
    with source_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("final_status", "")).strip().lower() != "success":
                continue
            doi = str(row.get("doi", "")).strip()
            offline = str(row.get("offline_html_path", "")).strip()
            if not doi or not offline:
                continue
            rows.append(dict(row))
    rows.sort(key=lambda r: (_parse_date(str(r.get("pub_date", ""))), str(r.get("doi", ""))), reverse=True)
    return rows[:n]


def _write_manifest_jsonl(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            payload = {
                "paper_id": str(r.get("doi", "")).strip(),
                "doi": str(r.get("doi", "")).strip(),
                "offline_html_path": str(r.get("offline_html_path", "")).strip(),
                "article_url": str(r.get("article_url", "")).strip(),
                "publication_date": str(r.get("pub_date", "")).strip(),
                "pub_date": str(r.get("pub_date", "")).strip(),
            }
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def main() -> None:
    args = parse_args()
    runs_root = ensure_runs_root(args.runs_root)
    run_id = args.run_id.strip() or utc_run_id(prefix=f"latest{int(args.n)}")
    rdir = run_dir(run_id, runs_root)
    rdir.mkdir(parents=True, exist_ok=True)

    latest_rows = _load_latest_rows(args.source_csv, args.n)
    if not latest_rows:
        raise RuntimeError("no eligible rows found from source csv")
    manifest_input = rdir / "manifest_input.jsonl"
    _write_manifest_jsonl(latest_rows, manifest_input)

    meta = {
        "run_id": run_id,
        "status": "created",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_rule": "latest_pub_date_desc",
        "sample_size": len(latest_rows),
        "source_csv": str(args.source_csv),
        "manifest_input": str(manifest_input),
        "model": args.model,
        "inference_mode": "batch",
    }
    write_json_atomic(rdir / "run_meta.json", meta)

    cmd = [
        "uv",
        "run",
        "python",
        "scripts/smj_pipeline/run_full_batch_inference.py",
        "--input-manifest",
        str(manifest_input),
        "--output-dir",
        str(rdir),
        "--model",
        str(args.model),
        "--api-key-env",
        str(args.api_key_env),
    ]
    if not args.no_submit:
        cmd.append("--submit")
    _run(cmd, Path.cwd())

    meta["status"] = "submitted" if not args.no_submit else "prepared"
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(rdir / "run_meta.json", meta)
    print(json.dumps({"run_id": run_id, "run_dir": str(rdir), "status": meta["status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
