from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


FIELDS = [
    "doi",
    "title",
    "pub_date",
    "article_url",
    "raw_html_path",
    "offline_html_path",
    "structured_md_path",
    "structure_report_path",
    "pdf_path",
    "html_ok",
    "pdf_ok",
    "final_status",
    "fail_reason",
    "updated_at",
]

STATUS_SCORE = {
    "success": 3,
    "running": 2,
    "failed": 1,
    "": 0,
}


def normalize_doi(doi: str) -> str:
    return (doi or "").strip().lower()


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def better_row(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    sa = STATUS_SCORE.get((a.get("final_status") or "").strip(), 0)
    sb = STATUS_SCORE.get((b.get("final_status") or "").strip(), 0)
    if sb > sa:
        return b
    if sb < sa:
        return a
    ua = a.get("updated_at", "")
    ub = b.get("updated_at", "")
    if ub > ua:
        return b
    if ua > ub:
        return a
    # Prefer rows with both html/pdf success flags if everything else ties.
    qa = int(a.get("html_ok") == "true") + int(a.get("pdf_ok") == "true")
    qb = int(b.get("html_ok") == "true") + int(b.get("pdf_ok") == "true")
    return b if qb > qa else a


def merge_rows(base: list[dict[str, str]], extra: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], int]:
    out: dict[str, dict[str, str]] = {}
    replaced = 0
    for row in base + extra:
        doi = normalize_doi(row.get("doi", ""))
        if not doi:
            continue
        row2 = {k: row.get(k, "") for k in FIELDS}
        row2["doi"] = doi
        if doi not in out:
            out[doi] = row2
            continue
        chosen = better_row(out[doi], row2)
        if chosen is row2:
            replaced += 1
        out[doi] = chosen
    return out, replaced


def main(args: argparse.Namespace) -> None:
    workers_root = Path(args.workers_root)
    worker_manifests = sorted(workers_root.glob("worker_*/manifest.csv"))
    if not worker_manifests:
        raise RuntimeError(f"No worker manifests found under: {workers_root}")

    base_rows: list[dict[str, str]] = []
    if args.base_manifest:
        base_rows = read_manifest(Path(args.base_manifest))

    extra_rows: list[dict[str, str]] = []
    per_worker_counts: dict[str, int] = {}
    for manifest in worker_manifests:
        rows = read_manifest(manifest)
        per_worker_counts[str(manifest)] = len(rows)
        extra_rows.extend(rows)

    merged, replaced = merge_rows(base_rows, extra_rows)
    out_manifest = Path(args.output_manifest)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    with out_manifest.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for doi in sorted(merged.keys()):
            writer.writerow(merged[doi])

    status_counts: dict[str, int] = {}
    for row in merged.values():
        s = row.get("final_status", "")
        status_counts[s] = status_counts.get(s, 0) + 1

    report = {
        "worker_manifests": len(worker_manifests),
        "per_worker_counts": per_worker_counts,
        "base_rows": len(base_rows),
        "extra_rows": len(extra_rows),
        "merged_rows": len(merged),
        "replaced_rows": replaced,
        "status_counts": status_counts,
    }
    out_report = Path(args.output_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote merged manifest: {out_manifest}")
    print(f"Wrote merge report: {out_report}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge SMJ worker manifests into one deduplicated manifest.")
    parser.add_argument("--workers-root", required=True, help="Directory containing worker_*/manifest.csv")
    parser.add_argument("--base-manifest", default="", help="Optional existing manifest used as base")
    parser.add_argument("--output-manifest", required=True)
    parser.add_argument("--output-report", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
