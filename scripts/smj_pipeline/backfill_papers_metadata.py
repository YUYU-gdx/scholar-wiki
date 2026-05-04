from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception as exc:  # pragma: no cover
    raise RuntimeError("psycopg is required. run: uv add psycopg[binary]") from exc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill papers metadata from workspace corpus indexes.")
    p.add_argument("--dsn", required=True)
    p.add_argument("--workspaces-root", type=Path, default=Path("outputs/workspaces"))
    return p.parse_args()


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def main() -> None:
    args = parse_args()
    updates = 0
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            for ws in args.workspaces_root.glob("*"):
                index_path = ws / "corpus" / "index" / "papers.ndjson"
                for row in _iter_jsonl(index_path):
                    paper_key = str(row.get("paper_key", "") or "").strip()
                    if not paper_key:
                        continue
                    meta_path = ws / "corpus" / "papers" / paper_key / "meta" / "paper.json"
                    meta = _read_json(meta_path)
                    paper_id = str(meta.get("paper_id", "") or row.get("paper_id", "") or row.get("doi", "")).strip()
                    if not paper_id:
                        continue
                    cur.execute(
                        """
                        UPDATE papers
                        SET
                          title = COALESCE(NULLIF(title, ''), %s),
                          authors_json = CASE
                            WHEN jsonb_typeof(authors_json) = 'array' AND jsonb_array_length(authors_json) > 0 THEN authors_json
                            ELSE %s::jsonb
                          END,
                          abstract = COALESCE(NULLIF(abstract, ''), %s),
                          journal = COALESCE(NULLIF(journal, ''), %s),
                          source_pdf_path = COALESCE(NULLIF(source_pdf_path, ''), %s),
                          source_md_path = COALESCE(NULLIF(source_md_path, ''), %s),
                          source_html_path = COALESCE(NULLIF(source_html_path, ''), %s)
                        WHERE paper_id = %s
                        """,
                        (
                            str(meta.get("title", "") or row.get("title", "") or ""),
                            json.dumps(meta.get("authors", []) or row.get("authors", []) or [], ensure_ascii=False),
                            str(meta.get("abstract", "") or ""),
                            str(meta.get("journal", "") or ""),
                            str(meta.get("source_pdf_path", "") or ""),
                            str(meta.get("md_path", "") or ""),
                            str(meta.get("html_path", "") or ""),
                            paper_id,
                        ),
                    )
                    updates += 1
        conn.commit()
    print(json.dumps({"updated_rows": updates}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
