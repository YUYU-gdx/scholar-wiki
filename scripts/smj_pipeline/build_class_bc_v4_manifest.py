from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from mineru_agent_common import canonical_pdf_name, find_pdf_for_doi, iter_jsonl, write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build class B/C PDF manifest for MinerU v4 precise API.")
    p.add_argument(
        "--class-b-manifest",
        type=Path,
        default=Path("outputs/smj_extraction_mvp/reclassified_full/manifest_class_b.jsonl"),
    )
    p.add_argument(
        "--class-c-manifest",
        type=Path,
        default=Path("outputs/smj_extraction_mvp/reclassified_full/manifest_class_c.jsonl"),
    )
    p.add_argument("--pdf-root", type=Path, default=Path("outputs/smj_merged_categorized/success/pdf"))
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--max-size-mb", type=int, default=200)
    p.add_argument("--max-pages", type=int, default=200)
    return p.parse_args()


def _collect_rows(path: Path, doc_class: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in iter_jsonl(path):
        doi = str(row.get("doi", "")).strip()
        if not doi:
            continue
        out.append({"doc_class": doc_class, "doi": doi})
    return out


def _pdf_page_count(path: Path) -> int:
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return -1


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    max_size_bytes = int(args.max_size_mb) * 1024 * 1024
    max_pages = int(args.max_pages)

    rows: list[dict[str, Any]] = []
    rows.extend(_collect_rows(args.class_b_manifest, "B"))
    rows.extend(_collect_rows(args.class_c_manifest, "C"))

    pdf_paths = list(args.pdf_root.rglob("*.pdf"))
    pdf_index = {canonical_pdf_name(p): p for p in pdf_paths}

    manifest_rows: list[dict[str, Any]] = []
    no_pdf_rows: list[dict[str, Any]] = []
    oversize_rows: list[dict[str, Any]] = []
    overpages_rows: list[dict[str, Any]] = []
    unreadable_rows: list[dict[str, Any]] = []

    for row in rows:
        doi = str(row["doi"])
        doc_class = str(row["doc_class"])
        pdf_path = find_pdf_for_doi(doi, pdf_index)
        if pdf_path is None:
            no_pdf_rows.append({"doc_class": doc_class, "doi": doi, "reason": "pdf_not_found"})
            continue

        file_size = int(pdf_path.stat().st_size)
        page_count = _pdf_page_count(pdf_path)
        eligible = True
        ineligible_reason = ""

        if file_size > max_size_bytes:
            eligible = False
            ineligible_reason = "oversize"
            oversize_rows.append(
                {
                    "doc_class": doc_class,
                    "doi": doi,
                    "pdf_path": str(pdf_path),
                    "file_size_bytes": file_size,
                    "max_size_bytes": max_size_bytes,
                }
            )
        elif page_count <= 0:
            eligible = False
            ineligible_reason = "pdf_unreadable"
            unreadable_rows.append(
                {
                    "doc_class": doc_class,
                    "doi": doi,
                    "pdf_path": str(pdf_path),
                    "file_size_bytes": file_size,
                    "page_count": page_count,
                }
            )
        elif page_count > max_pages:
            eligible = False
            ineligible_reason = "over_max_pages"
            overpages_rows.append(
                {
                    "doc_class": doc_class,
                    "doi": doi,
                    "pdf_path": str(pdf_path),
                    "file_size_bytes": file_size,
                    "page_count": page_count,
                    "max_pages": max_pages,
                }
            )

        manifest_rows.append(
            {
                "doc_class": doc_class,
                "doi": doi,
                "pdf_path": str(pdf_path),
                "file_name": pdf_path.name,
                "file_size_bytes": file_size,
                "page_count": page_count,
                "eligible": eligible,
                "ineligible_reason": ineligible_reason,
            }
        )

    write_jsonl(run_dir / "manifest_pdf_v4.jsonl", manifest_rows)
    write_jsonl(run_dir / "manifest_no_pdf_v4.jsonl", no_pdf_rows)
    write_jsonl(run_dir / "manifest_oversize_v4.jsonl", oversize_rows)
    write_jsonl(run_dir / "manifest_overpages_v4.jsonl", overpages_rows)
    write_jsonl(run_dir / "manifest_unreadable_v4.jsonl", unreadable_rows)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "run_dir": str(run_dir),
        "pdf_root": str(args.pdf_root),
        "class_b_total": sum(1 for r in rows if str(r.get("doc_class")) == "B"),
        "class_c_total": sum(1 for r in rows if str(r.get("doc_class")) == "C"),
        "total_input": len(rows),
        "manifest_rows": len(manifest_rows),
        "eligible_rows": sum(1 for r in manifest_rows if bool(r.get("eligible"))),
        "ineligible_rows": sum(1 for r in manifest_rows if not bool(r.get("eligible"))),
        "oversize_rows": len(oversize_rows),
        "overpages_rows": len(overpages_rows),
        "unreadable_rows": len(unreadable_rows),
        "no_pdf_rows": len(no_pdf_rows),
        "max_size_mb": int(args.max_size_mb),
        "max_pages": int(args.max_pages),
    }
    write_json(run_dir / "manifest_pdf_v4_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

