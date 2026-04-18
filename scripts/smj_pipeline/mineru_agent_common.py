from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                yield payload


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def canonical_pdf_name(path: Path) -> str:
    return normalize_key(path.stem)


def find_pdf_for_doi(doi: str, pdf_index: dict[str, Path]) -> Path | None:
    key = normalize_key(doi)
    if key in pdf_index:
        return pdf_index[key]

    m = re.search(r"1002smj\d+", key)
    if m:
        short = m.group(0)
        for idx_key, candidate in pdf_index.items():
            if short in idx_key:
                return candidate
    return None


def safe_id(text: str, max_len: int = 96) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(text or "").strip())
    slug = re.sub(r"_+", "_", slug).strip("._")
    if not slug:
        slug = "item"
    if len(slug) <= max_len:
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:10]
    head = slug[: max_len - 11]
    return f"{head}_{digest}"

