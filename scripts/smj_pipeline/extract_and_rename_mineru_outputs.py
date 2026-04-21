from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any
import zipfile

from mineru_agent_common import safe_id, write_json, write_json_atomic


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Unpack recovered MinerU zips and rename markdown outputs.")
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--index-jsonl", type=Path, default=None)
    ap.add_argument("--zips-dir", type=Path, default=None)
    return ap.parse_args()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            row = json.loads(t)
            if isinstance(row, dict):
                out.append(row)
    return out


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": {}, "updated_at": _now_iso()}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}, "updated_at": _now_iso()}
    if not isinstance(obj, dict):
        return {"items": {}, "updated_at": _now_iso()}
    if not isinstance(obj.get("items"), dict):
        obj["items"] = {}
    return obj


def _sanitize_name(s: str) -> str:
    text = str(s or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    return text[:180] if text else ""


def _first_h1(md_text: str) -> str:
    for line in str(md_text).splitlines():
        t = line.strip()
        if t.startswith("# "):
            return t[2:].strip()
    return ""


def _find_full_md(unpack_dir: Path) -> Path | None:
    preferred = unpack_dir / "full.md"
    if preferred.exists():
        return preferred
    matches = list(unpack_dir.rglob("full.md"))
    if matches:
        return matches[0]
    md_files = list(unpack_dir.rglob("*.md"))
    return md_files[0] if md_files else None


def _fallback_name(doi: str, batch_id: str) -> str:
    doi = str(doi or "").strip().lower()
    if doi:
        return _sanitize_name(doi.replace("/", "_"))
    return safe_id(batch_id, 120)


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir
    index_path = args.index_jsonl if args.index_jsonl else (run_dir / "recovered_batch_index.jsonl")
    zips_dir = args.zips_dir if args.zips_dir else (run_dir / "downloads" / "zips_raw")
    unpack_dir = run_dir / "downloads" / "unpacked"
    final_dir = run_dir / "downloads" / "final_named"
    checkpoint_path = run_dir / "checkpoint_unpack.json"

    unpack_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_jsonl(index_path)
    ckpt = _load_checkpoint(checkpoint_path)
    items: dict[str, Any] = ckpt.setdefault("items", {})

    for row in rows:
        batch_id = str(row.get("batch_id", "")).strip()
        if not batch_id:
            continue
        entry = items.get(batch_id, {})
        if not isinstance(entry, dict):
            entry = {}
        if str(entry.get("unpack_status", "")).lower() == "done":
            continue
        zip_path = zips_dir / f"{safe_id(batch_id, 120)}.zip"
        if not zip_path.exists():
            entry.update({"unpack_status": "failed", "error": f"zip_missing:{zip_path}", "updated_at": _now_iso()})
            items[batch_id] = entry
            ckpt["updated_at"] = _now_iso()
            write_json_atomic(checkpoint_path, ckpt)
            continue
        out_dir = unpack_dir / safe_id(batch_id, 120)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(out_dir)
            entry.update({"unpack_status": "done", "unpack_dir": str(out_dir), "updated_at": _now_iso()})
            _log(f"[unpack] done batch={batch_id}")
        except Exception as exc:
            entry.update({"unpack_status": "failed", "error": f"unzip_error:{type(exc).__name__}:{exc}", "updated_at": _now_iso()})
            _log(f"[unpack] failed batch={batch_id} error={entry.get('error')}")
        items[batch_id] = entry
        ckpt["updated_at"] = _now_iso()
        write_json_atomic(checkpoint_path, ckpt)

    # Build naming pool.
    named_rows: list[dict[str, Any]] = []
    title_counts: dict[str, int] = {}
    for row in rows:
        batch_id = str(row.get("batch_id", "")).strip()
        if not batch_id:
            continue
        entry = items.get(batch_id, {})
        if str(entry.get("unpack_status", "")).lower() != "done":
            continue
        one_unpack_dir = Path(str(entry.get("unpack_dir", "")))
        full_md_path = _find_full_md(one_unpack_dir)
        title = ""
        if full_md_path and full_md_path.exists():
            title = _first_h1(full_md_path.read_text(encoding="utf-8", errors="ignore"))
        title_key = title.strip().lower()
        if title_key:
            title_counts[title_key] = title_counts.get(title_key, 0) + 1
        named_rows.append(
            {
                "batch_id": batch_id,
                "doi_guess": str(row.get("doi_guess", "")).strip(),
                "title": title.strip(),
                "full_md_path": str(full_md_path) if full_md_path else "",
            }
        )

    used_names: set[str] = set()
    naming_map_rows: list[dict[str, str]] = []
    duplicate_report_rows: list[dict[str, str]] = []
    dup_groups: dict[str, list[str]] = {}

    for item in named_rows:
        batch_id = item["batch_id"]
        doi_guess = item["doi_guess"]
        title = item["title"]
        md_path = Path(item["full_md_path"]) if item["full_md_path"] else None
        title_key = title.strip().lower()

        if title_key and title_counts.get(title_key, 0) == 1:
            stem = _sanitize_name(title)
            naming_basis = "title"
        else:
            stem = _fallback_name(doi_guess, batch_id)
            naming_basis = "doi_or_batch"
            if title_key and title_counts.get(title_key, 0) > 1:
                dup_groups.setdefault(title_key, []).append(batch_id)

        if not stem:
            stem = safe_id(batch_id, 120)
            naming_basis = "batch_id"

        final_stem = stem
        i = 1
        while final_stem.lower() in used_names:
            i += 1
            final_stem = f"{stem}__{i}"
        used_names.add(final_stem.lower())

        out_path = final_dir / f"{final_stem}.md"
        if md_path and md_path.exists():
            shutil.copyfile(md_path, out_path)
            status = "done"
        else:
            status = "missing_md"
        naming_map_rows.append(
            {
                "batch_id": batch_id,
                "title": title,
                "doi_guess": doi_guess,
                "naming_basis": naming_basis,
                "final_name": f"{final_stem}.md",
                "final_path": str(out_path),
                "status": status,
            }
        )
        _log(f"[name] {batch_id} -> {final_stem}.md ({naming_basis})")

    for key, bids in sorted(dup_groups.items(), key=lambda x: x[0]):
        duplicate_report_rows.append({"title": key, "count": str(len(bids)), "batch_ids": ";".join(sorted(bids))})

    naming_csv = run_dir / "naming_map.csv"
    dup_csv = run_dir / "duplicate_title_report.csv"
    with naming_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["batch_id", "title", "doi_guess", "naming_basis", "final_name", "final_path", "status"],
        )
        writer.writeheader()
        for row in naming_map_rows:
            writer.writerow(row)

    with dup_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "count", "batch_ids"])
        writer.writeheader()
        for row in duplicate_report_rows:
            writer.writerow(row)

    summary = {
        "generated_at": _now_iso(),
        "run_dir": str(run_dir),
        "index_path": str(index_path),
        "zips_dir": str(zips_dir),
        "checkpoint_unpack": str(checkpoint_path),
        "unpack_done_count": sum(1 for v in items.values() if isinstance(v, dict) and str(v.get("unpack_status", "")).lower() == "done"),
        "naming_done_count": sum(1 for r in naming_map_rows if r["status"] == "done"),
        "duplicate_title_group_count": len(duplicate_report_rows),
        "naming_map_csv": str(naming_csv),
        "duplicate_title_report_csv": str(dup_csv),
        "final_dir": str(final_dir),
    }
    write_json(run_dir / "recovery_unpack_summary.json", summary)
    _log("summary " + json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

