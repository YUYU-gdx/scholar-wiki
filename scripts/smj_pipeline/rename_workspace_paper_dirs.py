from __future__ import annotations

import json
import re
from pathlib import Path

WS = Path(r"D:\KNGraphApp\libraries\workspaces\supply_chain")
PAPERS_DIR = WS / "corpus" / "papers"
INDEX = WS / "corpus" / "index" / "papers.ndjson"
GV = WS / "graph_views.json"


def safe_dir(name: str) -> str:
    t = re.sub(r'[<>:"/\\|?*]+', ' ', (name or '').strip())
    t = re.sub(r'\s+', ' ', t).strip().strip('. ')
    return t[:120] or 'untitled'


def replace_path_value(v: str, old: Path, new: Path) -> str:
    s = str(v or '')
    old_s = str(old)
    if s.startswith(old_s):
        return str(new) + s[len(old_s):]
    return s


def main() -> None:
    rows = [json.loads(x) for x in INDEX.read_text(encoding='utf-8').splitlines() if x.strip()]
    used: set[str] = set()
    dir_map: dict[str, str] = {}

    for row in rows:
        old_key = str(row.get('paper_key', '') or '').strip()
        if not old_key:
            continue
        title = str(row.get('display_title', '') or row.get('title', '') or row.get('paper_id', '')).strip()
        base = safe_dir(title)
        cand = base
        i = 2
        while cand.lower() in used:
            cand = f"{base} ({i})"
            i += 1
        used.add(cand.lower())
        dir_map[old_key] = cand

    renamed = 0
    for old_key, new_key in dir_map.items():
        if old_key == new_key:
            continue
        old_dir = PAPERS_DIR / old_key
        new_dir = PAPERS_DIR / new_key
        if not old_dir.exists():
            continue
        if new_dir.exists():
            continue
        old_dir.rename(new_dir)
        renamed += 1

    # rewrite index
    out_rows: list[dict] = []
    for row in rows:
        old_key = str(row.get('paper_key', '') or '').strip()
        new_key = dir_map.get(old_key, old_key)
        old_dir = PAPERS_DIR / old_key
        new_dir = PAPERS_DIR / new_key
        row['paper_key'] = new_key
        for k in ('html_path', 'source_md_path', 'source_pdf_path', 'mineru_output_path', 'mineru_main_md_path'):
            if k in row:
                row[k] = replace_path_value(str(row.get(k, '') or ''), old_dir, new_dir)
        out_rows.append(row)
    INDEX.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in out_rows) + '\n', encoding='utf-8')

    # rewrite meta files
    for new_key in dir_map.values():
        meta_path = PAPERS_DIR / new_key / 'meta' / 'paper.json'
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        old_key = str(meta.get('paper_key', '') or '')
        if old_key in dir_map:
            old_dir = PAPERS_DIR / old_key
        else:
            old_dir = PAPERS_DIR / old_key
        new_dir = PAPERS_DIR / new_key
        meta['paper_key'] = new_key
        for k in ('html_path', 'source_md_path', 'source_pdf_path', 'mineru_output_path', 'mineru_main_md_path'):
            if k in meta:
                meta[k] = replace_path_value(str(meta.get(k, '') or ''), old_dir, new_dir)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    # rewrite graph views paths
    if GV.exists():
        obj = json.loads(GV.read_text(encoding='utf-8'))
        pm = obj.get('paper_map', {}) if isinstance(obj, dict) else {}
        if isinstance(pm, dict):
            for _, v in pm.items():
                if not isinstance(v, dict):
                    continue
                # path-level rewrite by matching any old dir segment
                for old_key, new_key in dir_map.items():
                    old_dir = PAPERS_DIR / old_key
                    new_dir = PAPERS_DIR / new_key
                    for k in ('offline_html_path', 'source_md_path', 'source_pdf_path'):
                        if k in v:
                            v[k] = replace_path_value(str(v.get(k, '') or ''), old_dir, new_dir)
        GV.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')

    print(json.dumps({'renamed_dirs': renamed, 'total_rows': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
