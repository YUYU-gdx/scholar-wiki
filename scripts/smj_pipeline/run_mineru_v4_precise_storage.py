from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from run_registry import write_json_atomic


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run MinerU v4 precise pipeline by scanning PDFs directly from storage root.")
    p.add_argument("--pdf-root", type=Path, default=Path(r"D:\zoyerofile\storage"))
    p.add_argument("--run-root", type=Path, default=Path("outputs/mineru_v4_precise_storage"))
    p.add_argument("--run-id", default="")
    p.add_argument("--max-size-mb", type=int, default=200)
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument("--scan-limit", type=int, default=0, help="Only include first N scanned PDFs in manifest build.")
    p.add_argument("--limit", type=int, default=0, help="Only submit first N manifest rows to MinerU.")
    p.add_argument("--api-key-env", default="MINERU_API_KEY")
    p.add_argument("--base-url", default="https://mineru.net/api/v4")
    p.add_argument("--model-version", default="vlm")
    p.add_argument("--language", default="en")
    p.add_argument("--disable-table", action="store_true")
    p.add_argument("--is-ocr", action="store_true", default=False)
    p.add_argument("--disable-formula", action="store_true")
    p.add_argument("--submit-interval-seconds", type=float, default=2.0)
    p.add_argument("--poll-interval-seconds", type=float, default=8.0)
    p.add_argument("--max-poll-seconds", type=int, default=3600)
    p.add_argument("--max-inflight", type=int, default=1)
    p.add_argument(
        "--submission-mode",
        choices=("coupled", "decoupled"),
        default="decoupled",
        help="decoupled will continue submitting while polling/downloading existing tasks.",
    )
    p.add_argument(
        "--max-submitted-inflight",
        type=int,
        default=0,
        help="Only for submission-mode=decoupled. 0 means unlimited.",
    )
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--retry-delays", default="8,20,60")
    p.add_argument("--daily-page-limit", type=int, default=0)
    p.add_argument("--daily-file-limit", type=int, default=5000)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=str(Path.cwd()), text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed:{proc.returncode}:{' '.join(cmd)}")


def main() -> None:
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = args.run_id.strip() or f"run_{stamp}"
    run_dir = args.run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = run_dir / "manifest_pdf_v4.jsonl"
    run_meta = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "pdf_root": str(args.pdf_root),
        "created_at": datetime.now().isoformat(),
        "mode": "storage_pdf_direct_v4",
        "defaults": {
            "max_inflight": int(args.max_inflight),
            "submission_mode": str(args.submission_mode),
            "max_submitted_inflight": int(args.max_submitted_inflight),
            "submit_interval_seconds": float(args.submit_interval_seconds),
            "poll_interval_seconds": float(args.poll_interval_seconds),
            "daily_file_limit": int(args.daily_file_limit),
            "max_size_mb": int(args.max_size_mb),
            "max_pages": int(args.max_pages),
        },
    }
    write_json_atomic(run_dir / "run_meta.json", run_meta)

    build_cmd = [
        "uv",
        "run",
        "python",
        "scripts/smj_pipeline/build_storage_pdf_v4_manifest.py",
        "--pdf-root",
        str(args.pdf_root),
        "--run-dir",
        str(run_dir),
        "--max-size-mb",
        str(int(args.max_size_mb)),
        "--max-pages",
        str(int(args.max_pages)),
    ]
    if int(args.scan_limit) > 0:
        build_cmd.extend(["--limit", str(int(args.scan_limit))])
    _run(build_cmd)

    run_cmd = [
        "uv",
        "run",
        "python",
        "scripts/smj_pipeline/run_mineru_v4_precise_batch.py",
        "--manifest",
        str(manifest_path),
        "--run-dir",
        str(run_dir),
        "--api-key-env",
        str(args.api_key_env),
        "--base-url",
        str(args.base_url),
        "--model-version",
        str(args.model_version),
        "--language",
        str(args.language),
        "--submit-interval-seconds",
        str(float(args.submit_interval_seconds)),
        "--poll-interval-seconds",
        str(float(args.poll_interval_seconds)),
        "--max-poll-seconds",
        str(int(args.max_poll_seconds)),
        "--max-inflight",
        str(int(args.max_inflight)),
        "--submission-mode",
        str(args.submission_mode),
        "--max-submitted-inflight",
        str(int(args.max_submitted_inflight)),
        "--max-retries",
        str(int(args.max_retries)),
        "--retry-delays",
        str(args.retry_delays),
        "--daily-page-limit",
        str(int(args.daily_page_limit)),
        "--daily-file-limit",
        str(int(args.daily_file_limit)),
        "--seed",
        str(int(args.seed)),
    ]
    if bool(args.disable_table):
        run_cmd.append("--disable-table")
    if bool(args.is_ocr):
        run_cmd.append("--is-ocr")
    if bool(args.disable_formula):
        run_cmd.append("--disable-formula")
    if int(args.limit) > 0:
        run_cmd.extend(["--limit", str(int(args.limit))])
    _run(run_cmd)

    result = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "manifest": str(manifest_path),
        "summary": str(run_dir / "run_v4_summary.json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
