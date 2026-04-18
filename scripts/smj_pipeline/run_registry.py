from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


DEFAULT_RUNS_ROOT = Path("outputs/runs")
DEFAULT_ACTIVE_PATH = DEFAULT_RUNS_ROOT / "active.json"


def utc_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}"


def ensure_runs_root(path: Path | str = DEFAULT_RUNS_ROOT) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir(run_id: str, runs_root: Path | str = DEFAULT_RUNS_ROOT) -> Path:
    return Path(runs_root) / run_id


def active_path(runs_root: Path | str = DEFAULT_RUNS_ROOT) -> Path:
    return Path(runs_root) / "active.json"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_active(runs_root: Path | str = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    p = active_path(runs_root)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def set_active(run_id: str, graph_views: Path, runs_root: Path | str = DEFAULT_RUNS_ROOT) -> Path:
    p = active_path(runs_root)
    write_json_atomic(
        p,
        {
            "run_id": run_id,
            "graph_views": str(graph_views),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return p
