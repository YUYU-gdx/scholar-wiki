from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_registry import DEFAULT_RUNS_ROOT, run_dir, set_active


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Activate one run for frontend/API by writing outputs/runs/active.json")
    p.add_argument("--run-id", required=True)
    p.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    p.add_argument("--graph-views", type=Path, default=None, help="Optional explicit graph_views.json path")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rdir = run_dir(args.run_id, args.runs_root)
    graph_views = args.graph_views or (rdir / "graph_views.json")
    if not graph_views.exists():
        raise RuntimeError(f"graph_views.json not found: {graph_views}")
    active = set_active(args.run_id, graph_views, args.runs_root)
    print(
        json.dumps(
            {
                "active_file": str(active),
                "run_id": args.run_id,
                "graph_views": str(graph_views),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

