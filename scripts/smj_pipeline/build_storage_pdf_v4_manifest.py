from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from mineru_agent_common import write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build MinerU v4 precise manifest by scanning PDFs from a directory.")
    p.add_argument("--pdf-root", type=Path, default=Path(r"D:\zoyerofile\storage"))
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--max-size-mb", type=int, default=200)
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument("--limit", type=int, default=0, help="Only include first N discovered PDFs (0 means all).")
    return p.parse_args()


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz  # type: ignore

        with fitz.open(str(path)) as doc:
            return int(doc.page_count)
    except Exception:
        return -1


def _source_id(pdf_root: Path, pdf_path: Path) -> str:
    rel = pdf_path.relative_to(pdf_root).as_posix()
    return f"storage::{rel}"


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    pdf_root = args.pdf_root
    if not pdf_root.exists():
        raise RuntimeError(f"pdf_root_not_found:{pdf_root}")

    max_size_bytes = int(args.max_size_mb) * 1024 * 1024
    max_pages = int(args.max_pages)

    pdf_paths = sorted(pdf_root.rglob("*.pdf"))
    if int(args.limit) > 0:
        pdf_paths = pdf_paths[: int(args.limit)]

    manifest_rows: list[dict[str, object]] = []
    oversize_rows: list[dict[str, object]] = []
    overpages_rows: list[dict[str, object]] = []
    unreadable_rows: list[dict[str, object]] = []

    for pdf_path in pdf_paths:
        file_size = int(pdf_path.stat().st_size)
        page_count = _pdf_page_count(pdf_path)
        sid = _source_id(pdf_root, pdf_path)
        eligible = True
        ineligible_reason = ""

        if file_size > max_size_bytes:
            eligible = False
            ineligible_reason = "oversize"
            oversize_rows.append(
                {
                    "source_id": sid,
                    "doi": sid,
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
                    "source_id": sid,
                    "doi": sid,
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
                    "source_id": sid,
                    "doi": sid,
                    "pdf_path": str(pdf_path),
                    "file_size_bytes": file_size,
                    "page_count": page_count,
                    "max_pages": max_pages,
                }
            )

        manifest_rows.append(
            {
                "doc_class": "storage",
                "source_id": sid,
                "doi": sid,
                "pdf_path": str(pdf_path),
                "file_name": pdf_path.name,
                "file_size_bytes": file_size,
                "page_count": page_count,
                "eligible": eligible,
                "ineligible_reason": ineligible_reason,
            }
        )

    write_jsonl(run_dir / "manifest_pdf_v4.jsonl", manifest_rows)
    write_jsonl(run_dir / "manifest_oversize_v4.jsonl", oversize_rows)
    write_jsonl(run_dir / "manifest_overpages_v4.jsonl", overpages_rows)
    write_jsonl(run_dir / "manifest_unreadable_v4.jsonl", unreadable_rows)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "run_dir": str(run_dir),
        "pdf_root": str(pdf_root),
        "total_discovered_pdfs": len(pdf_paths),
        "manifest_rows": len(manifest_rows),
        "eligible_rows": sum(1 for r in manifest_rows if bool(r.get("eligible"))),
        "ineligible_rows": sum(1 for r in manifest_rows if not bool(r.get("eligible"))),
        "oversize_rows": len(oversize_rows),
        "overpages_rows": len(overpages_rows),
        "unreadable_rows": len(unreadable_rows),
        "max_size_mb": int(args.max_size_mb),
        "max_pages": int(args.max_pages),
        "limit": int(args.limit),
    }
    write_json(run_dir / "manifest_pdf_v4_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
