from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Iterator


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            obj = json.loads(t)
            if isinstance(obj, dict):
                yield obj


def _resolve_html(row: dict[str, Any], root: Path) -> str:
    direct = str(row.get("html", "") or "")
    if direct.strip():
        return direct
    for key in ("offline_html_path", "raw_html_path", "html_path", "full_html_path"):
        value = str(row.get(key, "") or "").strip()
        if not value:
            continue
        p = Path(value)
        if not p.is_absolute():
            p = root / p
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reclassify manifest rows into Class A/B/C with current qualifier.")
    p.add_argument(
        "--input-manifest",
        type=Path,
        default=Path("outputs/smj_extraction_mvp/manifest_from_success_nobom.jsonl"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/smj_extraction_mvp/reclassified_full"),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    qualifier_mod = _load_module(
        "smj_pipeline_extraction_qualifier_reclassify",
        root / "scripts" / "smj_pipeline" / "extraction" / "qualifier.py",
    )

    all_rows: list[dict[str, Any]] = []
    class_a_rows: list[dict[str, Any]] = []
    class_b_rows: list[dict[str, Any]] = []
    class_c_rows: list[dict[str, Any]] = []
    missing_html_rows: list[dict[str, Any]] = []

    for row in _iter_jsonl(args.input_manifest):
        payload = dict(row)
        html = _resolve_html(row, root)
        if not html.strip():
            payload["doc_class"] = "C"
            payload["doc_class_reason"] = "missing_html"
            all_rows.append(payload)
            class_c_rows.append(payload)
            missing_html_rows.append(payload)
            continue
        q = qualifier_mod.classify_document(html)
        doc_class = str(getattr(q, "doc_class", "C"))
        payload["doc_class"] = doc_class
        all_rows.append(payload)
        if doc_class == "A":
            class_a_rows.append(payload)
        elif doc_class == "B":
            class_b_rows.append(payload)
        else:
            class_c_rows.append(payload)

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "manifest_reclassified_all.jsonl", all_rows)
    _write_jsonl(out_dir / "manifest_class_a.jsonl", class_a_rows)
    _write_jsonl(out_dir / "manifest_class_b.jsonl", class_b_rows)
    _write_jsonl(out_dir / "manifest_class_c.jsonl", class_c_rows)
    _write_jsonl(out_dir / "manifest_missing_html.jsonl", missing_html_rows)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_manifest": str(args.input_manifest),
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
