from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from typing import Any


def _safe_segment(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    out: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch in {"_", "-", "."}:
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("._-")
    return re.sub(r"_+", "_", cleaned)


def _extract_md_headings(md_text: str) -> list[tuple[int, str, int]]:
    headings: list[tuple[int, str, int]] = []
    for idx, line in enumerate(str(md_text or "").splitlines()):
        text = line.strip()
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", text)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        if title:
            headings.append((level, title, idx))
    return headings


def _is_abstract_heading(text: str) -> bool:
    normalized = re.sub(r"[\s\-_]+", "", str(text or "").strip().lower())
    return normalized in {"abstract", "summary", "摘要"}


def _paper_id_from_md(md_text: str, fallback: str) -> str:
    headings = _extract_md_headings(md_text)
    h1s = [(title, line_no) for level, title, line_no in headings if level == 1]
    if not h1s:
        return _safe_segment(fallback) or uuid.uuid4().hex
    chosen = h1s[0][0].strip()
    if len(h1s) >= 2:
        first_line = h1s[0][1]
        second_title, second_line = h1s[1]
        between = str(md_text or "").splitlines()[first_line + 1 : second_line]
        only_blank_between = all(not str(x).strip() for x in between)
        if only_blank_between:
            first_h2_under_second = ""
            for level, title, line_no in headings:
                if line_no <= second_line:
                    continue
                if level == 1:
                    break
                if level == 2:
                    first_h2_under_second = title
                    break
            if first_h2_under_second and not _is_abstract_heading(first_h2_under_second):
                chosen = second_title.strip()
    return _safe_segment(chosen) or _safe_segment(fallback) or uuid.uuid4().hex


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update_nested(obj: Any, mapping: dict[str, str]) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            nk = mapping.get(k, k)
            out[nk] = _update_nested(v, mapping)
        return out
    if isinstance(obj, list):
        return [_update_nested(v, mapping) for v in obj]
    if isinstance(obj, str):
        return mapping.get(obj, obj)
    return obj


def _find_md_path(meta: dict[str, Any], paper_dir: Path) -> Path | None:
    candidates: list[Path] = []
    source_md = str(meta.get("source_md_path", "") or "").strip()
    if source_md:
        candidates.append(Path(source_md))
    candidates.extend(sorted((paper_dir / "source").glob("*.md")))
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def migrate_workspace(workspace_root: Path) -> dict[str, Any]:
    papers_root = workspace_root / "corpus" / "papers"
    if not papers_root.exists():
        raise RuntimeError(f"papers dir not found: {papers_root}")

    id_map: dict[str, str] = {}
    meta_paths = sorted(papers_root.glob("*/meta/paper.json"))
    changed_meta = 0
    skipped = 0
    for meta_path in meta_paths:
        paper_dir = meta_path.parent.parent
        meta = _read_json(meta_path)
        old_id = str(meta.get("paper_id", "") or "").strip()
        md_path = _find_md_path(meta, paper_dir)
        if md_path is None:
            skipped += 1
            continue
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        fallback = old_id or str(meta.get("doi", "") or "") or paper_dir.name
        new_id = _paper_id_from_md(md_text, fallback=fallback)
        if not new_id:
            skipped += 1
            continue
        if old_id and old_id != new_id:
            id_map[old_id] = new_id
        meta["paper_id"] = new_id
        _write_json(meta_path, meta)
        changed_meta += 1

    papers_index = workspace_root / "corpus" / "index" / "papers.ndjson"
    changed_index = 0
    if papers_index.exists():
        rows_out: list[str] = []
        for line in papers_index.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            old_id = str(row.get("paper_id", "") or "").strip()
            if old_id in id_map:
                row["paper_id"] = id_map[old_id]
                changed_index += 1
            rows_out.append(json.dumps(row, ensure_ascii=False))
        papers_index.write_text("\n".join(rows_out) + ("\n" if rows_out else ""), encoding="utf-8")

    graph_path = workspace_root / "graph_views.json"
    changed_graph = False
    if graph_path.exists() and id_map:
        graph_obj = json.loads(graph_path.read_text(encoding="utf-8"))
        graph_new = _update_nested(graph_obj, id_map)
        _write_json(graph_path, graph_new)
        changed_graph = True

    lib_index = workspace_root / "corpus" / "index" / "library_index.json"
    changed_lib_index = False
    if lib_index.exists() and id_map:
        payload = _read_json(lib_index)
        pids = payload.get("paper_ids", [])
        if isinstance(pids, list):
            payload["paper_ids"] = sorted({id_map.get(str(x), str(x)) for x in pids if str(x).strip()})
            _write_json(lib_index, payload)
            changed_lib_index = True

    return {
        "workspace": str(workspace_root),
        "paper_dirs": len(meta_paths),
        "meta_updated": changed_meta,
        "skipped_no_md": skipped,
        "id_mapping_count": len(id_map),
        "papers_index_rows_updated": changed_index,
        "graph_updated": changed_graph,
        "library_index_updated": changed_lib_index,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite workspace paper_id from MD H1 rules and update references.")
    parser.add_argument("--workspace-root", required=True, help="Workspace root, e.g. D:/KNGraphApp/libraries/workspaces/supply_chain")
    args = parser.parse_args()
    result = migrate_workspace(Path(args.workspace_root).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
