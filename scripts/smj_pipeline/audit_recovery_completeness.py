from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from mineru_agent_common import write_json


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Audit completeness of recovered MinerU batch outputs.")
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--index-jsonl", type=Path, default=None)
    ap.add_argument("--checkpoint-download", type=Path, default=None)
    ap.add_argument("--checkpoint-unpack", type=Path, default=None)
    return ap.parse_args()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return obj if isinstance(obj, dict) else fallback


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            row = json.loads(t)
            if isinstance(row, dict):
                out.append(row)
    return out


def _manifest_dois(path: Path) -> list[str]:
    out: list[str] = []
    for row in _read_jsonl(path):
        doi = str(row.get("doi", "")).strip().lower()
        if doi:
            out.append(doi)
    return out


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir
    index_path = args.index_jsonl if args.index_jsonl else (run_dir / "recovered_batch_index.jsonl")
    cp_download = args.checkpoint_download if args.checkpoint_download else (run_dir / "checkpoint_download.json")
    cp_unpack = args.checkpoint_unpack if args.checkpoint_unpack else (run_dir / "checkpoint_unpack.json")

    manifest_dois = _manifest_dois(args.manifest)
    manifest_set = set(manifest_dois)
    index_rows = _read_jsonl(index_path)
    download_ckpt = _read_json(cp_download, {"candidates": {}})
    unpack_ckpt = _read_json(cp_unpack, {"items": {}})
    download_items = download_ckpt.get("candidates", {}) if isinstance(download_ckpt.get("candidates"), dict) else {}
    unpack_items = unpack_ckpt.get("items", {}) if isinstance(unpack_ckpt.get("items"), dict) else {}

    valid_batch_count = len(index_rows)
    download_done_count = sum(1 for v in download_items.values() if isinstance(v, dict) and str(v.get("status", "")).lower() == "done")
    unpack_done_count = sum(1 for v in unpack_items.values() if isinstance(v, dict) and str(v.get("unpack_status", "")).lower() == "done")

    mapped_manifest_dois: set[str] = set()
    orphan_rows: list[dict[str, str]] = []
    for row in index_rows:
        bid = str(row.get("batch_id", "")).strip()
        doi = str(row.get("doi_guess", "")).strip().lower()
        if doi and doi in manifest_set:
            mapped_manifest_dois.add(doi)
        else:
            orphan_rows.append(
                {
                    "batch_id": bid,
                    "doi_guess": doi,
                    "file_name": str(row.get("file_name", "")).strip(),
                    "state": str(row.get("state", "")).strip(),
                }
            )

    missing_dois = sorted(manifest_set - mapped_manifest_dois)
    coverage = round((len(mapped_manifest_dois) / len(manifest_set)) if manifest_set else 0.0, 6)

    missing_csv = run_dir / "missing_doi.csv"
    with missing_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["doi"])
        writer.writeheader()
        for doi in missing_dois:
            writer.writerow({"doi": doi})

    orphan_csv = run_dir / "orphan_batches.csv"
    with orphan_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["batch_id", "doi_guess", "file_name", "state"])
        writer.writeheader()
        for row in orphan_rows:
            writer.writerow(row)

    summary = {
        "generated_at": _now_iso(),
        "run_dir": str(run_dir),
        "manifest_path": str(args.manifest),
        "manifest_doi_total": len(manifest_set),
        "valid_batch_count": valid_batch_count,
        "zip_download_success_count": download_done_count,
        "unpack_success_count": unpack_done_count,
        "mapped_manifest_doi_count": len(mapped_manifest_dois),
        "coverage_ratio": coverage,
        "missing_doi_count": len(missing_dois),
        "orphan_batch_count": len(orphan_rows),
        "missing_doi_csv": str(missing_csv),
        "orphan_batches_csv": str(orphan_csv),
    }
    write_json(run_dir / "recovery_audit_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

