from __future__ import annotations

import argparse
import json
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_reusable_workflow", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def _run(cmd: list[str], cwd: Path) -> str:
    p = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)
    if p.stdout:
        print(p.stdout.rstrip())
    if p.stderr:
        print(p.stderr.rstrip(), file=sys.stderr)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return p.stdout


def _find_latest_run(prefix: str, runs_root: Path) -> Path:
    cands = [p for p in runs_root.glob(f"{prefix}*") if p.is_dir()]
    if not cands:
        raise RuntimeError(f"no run dir found under {runs_root} with prefix {prefix}")
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def _discover_batch_id(run_dir: Path) -> str:
    p = run_dir / "submit_summary.json"
    payload = json.loads(p.read_text(encoding="utf-8"))
    batches = payload.get("batches")
    if isinstance(batches, list) and batches:
        return str((batches[0] or {}).get("batch_id", "")).strip()
    return ""


def _wait_batch(batch_id: str, api_key: str, poll_seconds: int, max_minutes: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{BASE_URL}/batches/{batch_id}"
    loops = max(1, int((max_minutes * 60) / max(1, poll_seconds)))
    last: dict[str, Any] = {}
    for i in range(loops):
        r = requests.get(url, headers=headers, timeout=40)
        r.raise_for_status()
        last = r.json()
        status = str(last.get("status", ""))
        counts = last.get("request_counts", {})
        print(f"[BATCH] {i} status={status} counts={counts}")
        if status in {"completed", "failed", "expired", "cancelled"}:
            return last
        time.sleep(poll_seconds)
    return last


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reusable workflow: latest N extraction + finalize + LLM evaluation.")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--model", default="glm-4-plus")
    p.add_argument("--judge-model", default="glm-4-plus")
    p.add_argument("--runs-root", type=Path, default=Path("outputs/runs"))
    p.add_argument("--source-csv", type=Path, default=Path("outputs/smj_all_run/manifest.csv"))
    p.add_argument("--api-key-env", default="ZHIPU_API_KEY")
    p.add_argument("--poll-seconds", type=int, default=20)
    p.add_argument("--max-wait-minutes", type=int, default=240)
    p.add_argument("--gt-markdown", type=Path, default=None)
    p.add_argument("--activate", action="store_true")
    p.add_argument("--skip-submit", action="store_true")
    p.add_argument("--skip-wait", action="store_true")
    return p.parse_args()


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    cwd = Path.cwd()
    run_latest_cmd = [
        "uv",
        "run",
        "python",
        "scripts/smj_pipeline/run_latest_n_batch.py",
        "--source-csv",
        str(args.source_csv),
        "--n",
        str(args.n),
        "--model",
        str(args.model),
        "--runs-root",
        str(args.runs_root),
        "--api-key-env",
        str(args.api_key_env),
    ]
    if args.skip_submit:
        run_latest_cmd.append("--no-submit")

    _run(run_latest_cmd, cwd)
    run_dir = _find_latest_run(prefix=f"latest{int(args.n)}_", runs_root=args.runs_root)
    run_id = run_dir.name

    if args.skip_submit:
        print(json.dumps({"run_id": run_id, "run_dir": str(run_dir), "status": "prepared_only"}, ensure_ascii=False, indent=2))
        return

    batch_id = _discover_batch_id(run_dir)
    if not batch_id:
        raise RuntimeError(f"no batch_id found in {run_dir / 'submit_summary.json'}")

    key = os.getenv(args.api_key_env, "").strip()
    if not key:
        raise RuntimeError(f"missing api key env: {args.api_key_env}")

    status_payload: dict[str, Any] = {}
    if not args.skip_wait:
        status_payload = _wait_batch(batch_id, key, args.poll_seconds, args.max_wait_minutes)
        status = str(status_payload.get("status", ""))
        if status != "completed":
            raise RuntimeError(f"batch not completed, current status={status}")

    finalize_cmd = [
        "uv",
        "run",
        "python",
        "scripts/smj_pipeline/finalize_batch_run.py",
        "--run-id",
        run_id,
        "--runs-root",
        str(args.runs_root),
        "--batch-id",
        batch_id,
        "--api-key-env",
        str(args.api_key_env),
    ]
    if args.activate:
        finalize_cmd.append("--activate")
    _run(finalize_cmd, cwd)

    eval_cmd = [
        "uv",
        "run",
        "python",
        "scripts/smj_pipeline/evaluate_run_with_llm.py",
        "--run-dir",
        str(run_dir),
        "--model",
        str(args.judge_model),
        "--api-key-env",
        str(args.api_key_env),
    ]
    if args.gt_markdown:
        eval_cmd.extend(["--gt-markdown", str(args.gt_markdown)])
    _run(eval_cmd, cwd)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "batch_id": batch_id,
                "workflow": "completed",
                "gt_mode": bool(args.gt_markdown),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
