from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


_MOJIBAKE_RE = re.compile(r"[锟�ÃÂÐÑ¤¦]")


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, dict):
                yield obj


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def _resolve_html(path_text: str) -> str:
    p = Path(path_text)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _has_encoding_issue(text: str) -> bool:
    if not text:
        return True
    if "\ufffd" in text:
        return True
    if _MOJIBAKE_RE.search(text):
        return True
    return False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Drop encoding-corrupted rows from base dataset by scanning normalized HTML.")
    p.add_argument(
        "--input-jsonl",
        type=Path,
        default=Path("outputs/literature_base/base_dataset.jsonl"),
    )
    p.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("outputs/literature_base/base_dataset_clean.jsonl"),
    )
    p.add_argument(
        "--rejected-jsonl",
        type=Path,
        default=Path("outputs/literature_base/rejected_encoding_rows.jsonl"),
    )
    p.add_argument(
        "--summary-json",
        type=Path,
        default=Path("outputs/literature_base/encoding_clean_summary.json"),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for row in _iter_jsonl(args.input_jsonl):
        html_path = str(row.get("normalized_html_path", "") or "").strip()
        html_text = _resolve_html(html_path)
        if _has_encoding_issue(html_text):
            bad = dict(row)
            bad["reject_reason"] = "encoding_issue"
            dropped.append(bad)
            continue
        kept.append(dict(row))

    _write_jsonl(args.output_jsonl, kept)
    _write_jsonl(args.rejected_jsonl, dropped)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_jsonl": str(args.input_jsonl),
        "output_jsonl": str(args.output_jsonl),
        "rejected_jsonl": str(args.rejected_jsonl),
        "total_rows": len(kept) + len(dropped),
        "kept_rows": len(kept),
        "dropped_rows": len(dropped),
    }
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
