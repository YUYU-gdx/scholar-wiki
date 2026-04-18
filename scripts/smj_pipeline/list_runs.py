from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from run_registry import DEFAULT_RUNS_ROOT, load_active


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="List run directories and active run pointer")
    p.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    runs_root = Path(args.runs_root)
    active = load_active(runs_root)
    active_run_id = str(active.get("run_id", "")).strip()
    items: list[dict[str, Any]] = []
    if runs_root.exists():
        for child in sorted(runs_root.iterdir()):
            if not child.is_dir():
                continue
            meta = _safe_json(child / "run_meta.json")
            graph_views = child / "graph_views.json"
            submit_summary = _safe_json(child / "submit_summary.json")
            batch_id = ""
            if isinstance(submit_summary.get("batches"), list) and submit_summary["batches"]:
                batch_id = str((submit_summary["batches"][0] or {}).get("batch_id", "")).strip()
            items.append(
                {
                    "run_id": child.name,
                    "active": child.name == active_run_id,
                    "status": str(meta.get("status", "unknown")),
                    "created_at": str(meta.get("created_at", "")),
                    "graph_ready": graph_views.exists(),
                    "batch_id": batch_id,
                }
            )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_root": str(runs_root),
        "active": active,
        "runs": items,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
