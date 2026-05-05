from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from kn_graph.services.sqlite_repo import SqliteRepo


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if isinstance(row, dict):
                yield row


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import raw LLM JSONL outputs into SQLite as source-of-truth tables.")
    p.add_argument("--db-path", required=True, help="Path to SQLite database file.")
    p.add_argument("--raw-output-jsonl", type=Path, required=True)
    p.add_argument("--apply-schema", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    _repo_root = Path(__file__).resolve().parents[3]
    extractor = _load_module(
        "smj_pipeline_extractor_import_raw",
        _repo_root / "scripts" / "smj_pipeline" / "extraction" / "extractor.py",
    )

    total = 0
    ok = 0
    failed = 0

    db_path = Path(args.db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    repo = SqliteRepo(conn)
    if args.apply_schema:
        repo.apply_schema()

    for row in _iter_jsonl(args.raw_output_jsonl):
        total += 1
        if str(row.get("status", "")).strip() != "ok":
            failed += 1
            continue

        paper_id = str(row.get("paper_id", "") or row.get("doi", "")).strip()
        if not paper_id:
            failed += 1
            continue

        raw_response = str(row.get("raw_response", "") or "")
        try:
            bundle = extractor.parse_extraction_response(raw_response)
        except Exception:
            failed += 1
            continue

        payload: dict[str, Any] = {
            "doi": str(row.get("doi", "") or paper_id),
            "offline_html_path": str(row.get("offline_html_path", "") or row.get("full_html_path", "") or ""),
            "article_url": str(row.get("article_url", "") or ""),
            "publication_date": str(row.get("publication_date", "") or row.get("pub_date", "") or ""),
            "online_date": str(row.get("online_date", "") or ""),
            "publication_year": _coerce_optional_int(row.get("publication_year") or row.get("pub_year") or row.get("year")),
            "paper_citation_count": _coerce_optional_int(row.get("paper_citation_count") or row.get("citation_count")),
            "metadata_source": "raw_output_jsonl",
            "paper_domains": list(getattr(bundle, "paper_domains", []) or []),
            "extractability_status": getattr(bundle, "extractability_status", ""),
            "paper_type": getattr(bundle, "paper_type", ""),
            "extractability_reason": getattr(bundle, "extractability_reason", ""),
            "extractability_evidence_section": getattr(bundle, "extractability_evidence_section", ""),
            "variable_definitions": list(getattr(bundle, "variable_definitions", []) or []),
            "direct_effects": list(getattr(bundle, "direct_effects", []) or []),
            "moderations": list(getattr(bundle, "moderations", []) or []),
            "interactions": list(getattr(bundle, "interactions", []) or []),
        }
        repo.replace_paper_bundle(paper_id, payload)
        ok += 1

    conn.close()

    print(
        json.dumps(
            {
                "raw_output_jsonl": str(args.raw_output_jsonl),
                "total_rows": total,
                "ok_rows": ok,
                "failed_rows": failed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main_inline(*, db_path: str, raw_output_jsonl: Path, apply_schema: bool = False) -> dict[str, Any]:
    """Programmatic entry point used by pipeline_runtime."""
    _repo_root = Path(__file__).resolve().parents[3]
    extractor = _load_module(
        "smj_pipeline_extractor_import_inline",
        _repo_root / "scripts" / "smj_pipeline" / "extraction" / "extractor.py",
    )

    total = 0
    ok = 0
    failed = 0

    db = Path(db_path).resolve()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    repo = SqliteRepo(conn)
    if apply_schema:
        repo.apply_schema()

    for row in _iter_jsonl(raw_output_jsonl):
        total += 1
        if str(row.get("status", "")).strip() != "ok":
            failed += 1
            continue
        paper_id = str(row.get("paper_id", "") or row.get("doi", "")).strip()
        if not paper_id:
            failed += 1
            continue
        raw_response = str(row.get("raw_response", "") or "")
        try:
            bundle = extractor.parse_extraction_response(raw_response)
        except Exception:
            failed += 1
            continue
        payload: dict[str, Any] = {
            "doi": str(row.get("doi", "") or paper_id),
            "offline_html_path": str(row.get("offline_html_path", "") or row.get("full_html_path", "") or ""),
            "article_url": str(row.get("article_url", "") or ""),
            "publication_date": str(row.get("publication_date", "") or row.get("pub_date", "") or ""),
            "online_date": str(row.get("online_date", "") or ""),
            "publication_year": _coerce_optional_int(row.get("publication_year") or row.get("pub_year") or row.get("year")),
            "paper_citation_count": _coerce_optional_int(row.get("paper_citation_count") or row.get("citation_count")),
            "metadata_source": "raw_output_jsonl",
            "paper_domains": list(getattr(bundle, "paper_domains", []) or []),
            "extractability_status": getattr(bundle, "extractability_status", ""),
            "paper_type": getattr(bundle, "paper_type", ""),
            "extractability_reason": getattr(bundle, "extractability_reason", ""),
            "extractability_evidence_section": getattr(bundle, "extractability_evidence_section", ""),
            "variable_definitions": list(getattr(bundle, "variable_definitions", []) or []),
            "direct_effects": list(getattr(bundle, "direct_effects", []) or []),
            "moderations": list(getattr(bundle, "moderations", []) or []),
            "interactions": list(getattr(bundle, "interactions", []) or []),
        }
        repo.replace_paper_bundle(paper_id, payload)
        ok += 1

    conn.close()
    return {"total_rows": total, "ok_rows": ok, "failed_rows": failed}


if __name__ == "__main__":
    main()
