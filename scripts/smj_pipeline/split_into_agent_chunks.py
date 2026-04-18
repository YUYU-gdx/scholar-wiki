from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from mineru_agent_common import iter_jsonl, safe_id, write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Split eligible PDFs into MinerU agent chunks by page_range.")
    p.add_argument("--manifest-pdf", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--chunk-pages", type=int, default=20)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.chunk_pages <= 0:
        raise RuntimeError("chunk-pages must be > 0")

    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = list(iter_jsonl(args.manifest_pdf))
    chunk_rows: list[dict[str, object]] = []
    skipped_rows: list[dict[str, object]] = []

    for row in rows:
        doi = str(row.get("doi", "")).strip()
        if not doi:
            continue
        doc_class = str(row.get("doc_class", "")).strip()
        eligible = bool(row.get("eligible"))
        page_count = int(row.get("page_count", -1) or -1)
        pdf_path = str(row.get("pdf_path", "")).strip()
        file_name = str(row.get("file_name", "")).strip()

        if not eligible:
            skipped_rows.append(
                {
                    "doc_class": doc_class,
                    "doi": doi,
                    "pdf_path": pdf_path,
                    "reason": str(row.get("ineligible_reason", "")).strip() or "ineligible",
                }
            )
            continue
        if page_count <= 0:
            skipped_rows.append(
                {"doc_class": doc_class, "doi": doi, "pdf_path": pdf_path, "reason": "invalid_page_count"}
            )
            continue

        chunk_idx = 0
        for start in range(1, page_count + 1, int(args.chunk_pages)):
            end = min(page_count, start + int(args.chunk_pages) - 1)
            chunk_id = safe_id(f"{doi}__{start}-{end}")
            chunk_rows.append(
                {
                    "chunk_id": chunk_id,
                    "doc_class": doc_class,
                    "doi": doi,
                    "pdf_path": pdf_path,
                    "file_name": file_name,
                    "chunk_index": chunk_idx,
                    "page_start": start,
                    "page_end": end,
                    "page_range": f"{start}-{end}",
                    "source_page_count": page_count,
                }
            )
            chunk_idx += 1

    write_jsonl(run_dir / "manifest_chunks.jsonl", chunk_rows)
    write_jsonl(run_dir / "manifest_chunks_skipped.jsonl", skipped_rows)

    by_doi: dict[str, int] = {}
    for row in chunk_rows:
        doi = str(row.get("doi", ""))
        by_doi[doi] = by_doi.get(doi, 0) + 1

    summary = {
        "generated_at": datetime.now().isoformat(),
        "run_dir": str(run_dir),
        "manifest_pdf": str(args.manifest_pdf),
        "chunk_pages": int(args.chunk_pages),
        "chunk_rows": len(chunk_rows),
        "papers_with_chunks": len(by_doi),
        "skipped_rows": len(skipped_rows),
    }
    write_json(run_dir / "manifest_chunks_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

