from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from mineru_agent_common import iter_jsonl, safe_id, write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge MinerU chunk markdown files into one markdown per DOI.")
    p.add_argument("--manifest-chunks", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, default=None)
    return p.parse_args()


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"chunks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"chunks": {}}


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir
    md_root = run_dir / "md_chunks"
    merged_root = run_dir / "md_merged"
    merged_root.mkdir(parents=True, exist_ok=True)

    checkpoint_path = args.checkpoint or (run_dir / "checkpoint.json")
    checkpoint = _load_checkpoint(checkpoint_path)
    chunks_state = checkpoint.get("chunks", {})
    if not isinstance(chunks_state, dict):
        chunks_state = {}

    by_doi: dict[str, list[dict[str, Any]]] = {}
    for row in iter_jsonl(args.manifest_chunks):
        doi = str(row.get("doi", "")).strip()
        if not doi:
            continue
        by_doi.setdefault(doi, []).append(row)

    report_rows: list[dict[str, Any]] = []
    merged_count = 0
    partial_count = 0

    for doi, rows in by_doi.items():
        rows.sort(key=lambda r: int(r.get("chunk_index", 0) or 0))
        merged_parts: list[str] = []
        missing: list[dict[str, Any]] = []

        for row in rows:
            chunk_id = str(row.get("chunk_id", "")).strip()
            state = chunks_state.get(chunk_id) if isinstance(chunks_state.get(chunk_id), dict) else {}
            status = str((state or {}).get("status", "")).strip().lower()
            md_path = str((state or {}).get("md_chunk_path", "")).strip()
            if status != "done" or not md_path:
                missing.append(
                    {
                        "chunk_id": chunk_id,
                        "chunk_index": row.get("chunk_index"),
                        "page_range": row.get("page_range"),
                        "reason": f"status={status or 'unknown'}",
                    }
                )
                continue
            path = Path(md_path)
            if not path.exists():
                missing.append(
                    {
                        "chunk_id": chunk_id,
                        "chunk_index": row.get("chunk_index"),
                        "page_range": row.get("page_range"),
                        "reason": "md_chunk_missing",
                    }
                )
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            header = f"<!-- chunk:{chunk_id} pages:{row.get('page_range','')} -->"
            merged_parts.append(f"{header}\n\n{text}".strip())

        out_name = f"{safe_id(doi, max_len=120)}.md"
        out_path = merged_root / out_name
        if not missing and merged_parts:
            merged_text = "\n\n\n".join(merged_parts).strip() + "\n"
            out_path.write_text(merged_text, encoding="utf-8")
            merged_count += 1
            report_rows.append(
                {
                    "doi": doi,
                    "status": "merged",
                    "chunk_count": len(rows),
                    "merged_chunk_count": len(merged_parts),
                    "output_md": str(out_path),
                }
            )
        else:
            partial_count += 1
            report_rows.append(
                {
                    "doi": doi,
                    "status": "partial",
                    "chunk_count": len(rows),
                    "merged_chunk_count": len(merged_parts),
                    "missing_chunks": missing,
                    "output_md": str(out_path) if merged_parts else "",
                }
            )
            if merged_parts:
                partial_text = "\n\n\n".join(merged_parts).strip() + "\n"
                out_path.write_text(partial_text, encoding="utf-8")

    write_jsonl(run_dir / "merge_report.jsonl", report_rows)
    summary = {
        "generated_at": datetime.now().isoformat(),
        "run_dir": str(run_dir),
        "manifest_chunks": str(args.manifest_chunks),
        "checkpoint": str(checkpoint_path),
        "paper_total": len(by_doi),
        "merged_total": merged_count,
        "partial_total": partial_count,
        "md_merged_dir": str(merged_root),
    }
    write_json(run_dir / "merge_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

