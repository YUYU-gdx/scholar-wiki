from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main(args: argparse.Namespace) -> None:
    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    input_csv = args.input_csv
    if args.build_input_csv:
        input_path = Path(args.build_input_csv)
        if args.refresh_input or not input_path.exists():
            cmd = [
                sys.executable,
                "scripts/smj_recent10_runner.py",
                "--all-history",
                "--save-works-csv",
                str(input_path),
                "--only-build-input",
            ]
            subprocess.run(cmd, check=True)
        input_csv = str(input_path)

    procs: list[subprocess.Popen[str]] = []
    for i in range(args.workers):
        worker_dir = root / f"worker_{i}"
        worker_dir.mkdir(parents=True, exist_ok=True)
        log_file = worker_dir / "run.log"
        cmd = [
            sys.executable,
            "scripts/smj_recent10_runner.py",
            "--all-history",
            "--headless",
            "--output-dir",
            str(worker_dir),
            "--workers",
            str(args.workers),
            "--worker-index",
            str(i),
        ]
        if input_csv:
            cmd.extend(["--input-csv", input_csv])

        with log_file.open("a", encoding="utf-8") as log:
            p = subprocess.Popen(cmd, stdout=log, stderr=log, text=True)
        procs.append(p)
        print(f"worker={i} pid={p.pid} log={log_file}")

    pids_path = root / "pids.txt"
    pids_path.write_text("\n".join(str(p.pid) for p in procs) + "\n", encoding="utf-8")
    print(f"Wrote PIDs: {pids_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch parallel SMJ headless workers with shard splitting.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output-root", default="outputs/smj_all_parallel_headless")
    parser.add_argument("--input-csv", default="", help="Optional fixed DOI input CSV for all workers")
    parser.add_argument(
        "--build-input-csv",
        default="",
        help="Build DOI input CSV once using Crossref before launching workers.",
    )
    parser.add_argument("--refresh-input", action="store_true", help="Rebuild --build-input-csv even if file exists.")
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
