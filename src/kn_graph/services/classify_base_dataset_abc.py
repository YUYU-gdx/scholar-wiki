from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterator

from kn_graph.services.extraction.qualifier import classify_document


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
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


def _resolve_html(row: dict[str, Any], project_root: Path) -> str:
    for key in ("normalized_html_path", "offline_html_path", "raw_html_path", "html_path", "full_html_path", "source_path"):
        value = str(row.get(key, "") or "").strip()
        if not value:
            continue
        p = Path(value)
        if not p.is_absolute():
            p = project_root / p
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Classify base dataset into Class A/B/C.")
    p.add_argument("--input-base-dataset", type=Path, default=Path("outputs/literature_base/base_dataset.jsonl"))
    p.add_argument("--output-dir", type=Path, default=Path("outputs/literature_base/class_abc"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path.cwd()

    all_rows: list[dict[str, Any]] = []
    class_a_rows: list[dict[str, Any]] = []
    class_b_rows: list[dict[str, Any]] = []
    class_c_rows: list[dict[str, Any]] = []
    missing_html_rows: list[dict[str, Any]] = []

    for row in _iter_jsonl(args.input_base_dataset):
        payload = dict(row)
        html = _resolve_html(row, project_root)
        if not html.strip():
            payload["doc_class"] = "C"
            payload["doc_class_reason"] = "missing_html"
            payload["doc_class_source"] = "base_dataset_qualifier"
            all_rows.append(payload)
            class_c_rows.append(payload)
            missing_html_rows.append(payload)
            continue

        q = classify_document(html)
        doc_class = str(getattr(q, "doc_class", "C"))
        payload["doc_class"] = doc_class
        payload["doc_class_source"] = "base_dataset_qualifier"
        payload["doc_class_flags"] = {
            "has_abstract": bool(getattr(q, "has_abstract", False)),
            "has_references": bool(getattr(q, "has_references", False)),
            "has_hypotheses_block": bool(getattr(q, "has_hypotheses_block", False)),
            "has_results_block": bool(getattr(q, "has_results_block", False)),
            "has_main_model_signal": bool(getattr(q, "has_main_model_signal", False)),
        }
        all_rows.append(payload)
        if doc_class == "A":
            class_a_rows.append(payload)
        elif doc_class == "B":
            class_b_rows.append(payload)
        else:
            class_c_rows.append(payload)

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "base_dataset_classified_all.jsonl", all_rows)
    _write_jsonl(out_dir / "base_dataset_class_a.jsonl", class_a_rows)
    _write_jsonl(out_dir / "base_dataset_class_b.jsonl", class_b_rows)
    _write_jsonl(out_dir / "base_dataset_class_c.jsonl", class_c_rows)
    _write_jsonl(out_dir / "base_dataset_missing_html.jsonl", missing_html_rows)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_base_dataset": str(args.input_base_dataset),
        "output_dir": str(out_dir),
        "total_rows": len(all_rows),
        "class_a_rows": len(class_a_rows),
        "class_b_rows": len(class_b_rows),
        "class_c_rows": len(class_c_rows),
        "missing_html_rows": len(missing_html_rows),
    }
    (out_dir / "classification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

