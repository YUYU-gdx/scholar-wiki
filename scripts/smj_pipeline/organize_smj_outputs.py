from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
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

PATH_FIELD_TO_SUBDIR = {
    "raw_html_path": "raw_html",
    "offline_html_path": "offline_html",
    "structured_md_path": "structured_md",
    "structure_report_path": "structure_report",
    "pdf_path": "pdf",
}


def normalize_doi(doi: str) -> str:
    return (doi or "").strip().lower()


def sanitize_doi(doi: str) -> str:
    raw = doi.replace("/", "_")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    if not safe:
        safe = "doi"
    if len(safe) > 120:
        digest = hashlib.md5(doi.encode("utf-8")).hexdigest()[:10]
        safe = f"{safe[:100]}_{digest}"
    return safe


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})


def main(args: argparse.Namespace) -> None:
    merged_manifest = Path(args.merged_manifest)
    out_root = Path(args.output_root)
    rows = read_manifest(merged_manifest)
    if not rows:
        raise RuntimeError(f"No rows in merged manifest: {merged_manifest}")

    manifests_dir = out_root / "manifests"
    success_root = out_root / "success"
    failed_root = out_root / "failed"
    running_root = out_root / "running"

    for d in [manifests_dir, success_root, failed_root, running_root]:
        d.mkdir(parents=True, exist_ok=True)

    success_rows: list[dict[str, str]] = []
    failed_rows: list[dict[str, str]] = []
    running_rows: list[dict[str, str]] = []

    copied_counts = {k: 0 for k in PATH_FIELD_TO_SUBDIR}
    missing_counts = {k: 0 for k in PATH_FIELD_TO_SUBDIR}

    for row in rows:
        doi = normalize_doi(row.get("doi", ""))
        if not doi:
            continue
        row["doi"] = doi
        status = (row.get("final_status") or "").strip().lower()

        if status == "success":
            success_rows.append(row)
            stem = sanitize_doi(doi)
            for field, subdir in PATH_FIELD_TO_SUBDIR.items():
                src_val = (row.get(field) or "").strip()
                if not src_val:
                    continue
                src = Path(src_val)
                if not src.is_absolute():
                    src = Path(args.project_root) / src
                ext = src.suffix or ".bin"
                dst = success_root / subdir / f"{stem}{ext}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.exists():
                    shutil.copy2(src, dst)
                    copied_counts[field] += 1
                else:
                    missing_counts[field] += 1
        elif status == "failed":
            failed_rows.append(row)
        elif status == "running":
            running_rows.append(row)

    write_manifest(manifests_dir / "merged_manifest.csv", rows)
    write_manifest(manifests_dir / "success_manifest.csv", success_rows)
    write_manifest(manifests_dir / "failed_manifest.csv", failed_rows)
    write_manifest(manifests_dir / "running_manifest.csv", running_rows)

    summary = {
        "merged_total": len(rows),
        "success_total": len(success_rows),
        "failed_total": len(failed_rows),
        "running_total": len(running_rows),
        "copied_counts": copied_counts,
        "missing_counts": missing_counts,
    }
    (manifests_dir / "organize_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote organized outputs to: {out_root}")
    print(json.dumps(summary, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Organize merged SMJ outputs by category.")
    p.add_argument("--merged-manifest", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--project-root", default=".")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())
