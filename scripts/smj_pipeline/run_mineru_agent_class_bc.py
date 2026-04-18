from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from run_registry import write_json_atomic


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-command runner for class B/C PDF parsing via MinerU agent API.")
    p.add_argument(
        "--run-root",
        type=Path,
        default=Path("outputs/mineru_agent_class_bc"),
    )
    p.add_argument("--run-id", default="")
    p.add_argument("--chunk-pages", type=int, default=20)
    p.add_argument("--limit-chunks", type=int, default=0, help="Smoke mode: only run first N pending chunks.")
    p.add_argument("--skip-manifest", action="store_true")
    p.add_argument("--skip-split", action="store_true")
    p.add_argument("--skip-run", action="store_true")
    p.add_argument("--skip-merge", action="store_true")
    return p.parse_args()


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=str(Path.cwd()), text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def main() -> None:
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = args.run_id.strip() or f"run_{stamp}"
    run_dir = args.run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_pdf = run_dir / "manifest_pdf.jsonl"
    manifest_chunks = run_dir / "manifest_chunks.jsonl"

    meta = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "created_at": datetime.now().isoformat(),
        "chunk_pages": int(args.chunk_pages),
        "limit_chunks": int(args.limit_chunks),
    }
    write_json_atomic(run_dir / "run_meta.json", meta)

    if not args.skip_manifest:
        _run(
            [
                "uv",
                "run",
                "python",
                "scripts/smj_pipeline/build_class_bc_pdf_manifest.py",
                "--run-dir",
                str(run_dir),
            ]
        )

    if not args.skip_split:
        _run(
            [
                "uv",
                "run",
                "python",
                "scripts/smj_pipeline/split_into_agent_chunks.py",
                "--manifest-pdf",
                str(manifest_pdf),
                "--run-dir",
                str(run_dir),
                "--chunk-pages",
                str(args.chunk_pages),
            ]
        )

    if not args.skip_run:
        cmd = [
            "uv",
            "run",
            "python",
            "scripts/smj_pipeline/run_agent_chunks_safe.py",
            "--manifest-chunks",
            str(manifest_chunks),
            "--run-dir",
            str(run_dir),
        ]
        if int(args.limit_chunks) > 0:
            cmd.extend(["--limit", str(int(args.limit_chunks))])
        _run(cmd)

    if not args.skip_merge:
        _run(
            [
                "uv",
                "run",
                "python",
                "scripts/smj_pipeline/merge_chunk_markdown.py",
                "--manifest-chunks",
                str(manifest_chunks),
                "--run-dir",
                str(run_dir),
            ]
        )

    result = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "manifest_pdf": str(manifest_pdf),
        "manifest_chunks": str(manifest_chunks),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

