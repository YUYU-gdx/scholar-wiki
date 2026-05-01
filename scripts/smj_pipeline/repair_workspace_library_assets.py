from __future__ import annotations

import html
import json
import re
from pathlib import Path
import argparse

WORKSPACES_ROOT = Path(r"D:\KNGraphApp\libraries\workspaces")


def safe_name(s: str) -> str:
    t = re.sub(r'[<>:"/\\|?*]+', '_', (s or '').strip())
    t = re.sub(r'\s+', ' ', t).strip().strip('. ')
    if not t:
        t = 'untitled'
    return t[:180]


def first_h1(md_text: str) -> str:
    for line in md_text.splitlines():
        txt = line.strip()
        if txt.startswith('# '):
            return txt[2:].strip()
    return ''


def html_to_md_text(raw_html: str) -> str:
    m = re.search(r'(?is)<pre[^>]*>(.*?)</pre>', raw_html)
    if m:
        return html.unescape(m.group(1)).strip() + '\n'
    text = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', raw_html)
    text = re.sub(r'(?i)</?(p|div|section|article|br|li|h[1-6]|tr|td|th|blockquote)[^>]*>', '\n', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def repair_one_workspace(workspace: Path) -> dict:
    papers_dir = workspace / "corpus" / "papers"
    index_path = workspace / "corpus" / "index" / "papers.ndjson"
    graph_views_path = workspace / "graph_views.json"
    mapping: dict[str, dict] = {}
    updated = 0

    for paper_dir in sorted(papers_dir.glob('*')):
        meta_path = paper_dir / 'meta' / 'paper.json'
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        paper_id = str(meta.get('paper_id', '') or '').strip()
        if not paper_id:
            continue

        html_dir = paper_dir / 'derived' / 'html'
        html_files = sorted(html_dir.glob('*.html'))
        if not html_files:
            continue
        html_path = html_files[0]
        raw_html = html_path.read_text(encoding='utf-8', errors='ignore')
        md_text = html_to_md_text(raw_html)

        title = first_h1(md_text)
        if not title:
            title = str(meta.get('display_title', '') or '').strip() or str(meta.get('title', '') or '').strip() or paper_id
        stem = safe_name(title)

        source_dir = paper_dir / 'source'
        source_dir.mkdir(parents=True, exist_ok=True)
        md_path = source_dir / f'{stem}.md'
        md_path.write_text(md_text, encoding='utf-8')

        new_html_path = html_dir / f'{stem}.html'
        if html_path.resolve() != new_html_path.resolve():
            if new_html_path.exists():
                new_html_path.unlink()
            html_path.rename(new_html_path)

        meta['title'] = title
        meta['display_title'] = title
        meta['source_md_path'] = str(md_path)
        meta['html_path'] = str(new_html_path)
        if not str(meta.get('source_pdf_name', '') or '').strip():
            meta['source_pdf_name'] = f'{stem}.pdf'
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

        mapping[paper_id] = {
            'title': title,
            'display_title': title,
            'source_md_path': str(md_path),
            'html_path': str(new_html_path),
            'source_pdf_name': str(meta.get('source_pdf_name', '') or ''),
        }
        updated += 1

    if index_path.exists():
        rows: list[dict] = []
        for line in index_path.read_text(encoding='utf-8').splitlines():
            txt = line.strip()
            if not txt:
                continue
            row = json.loads(txt)
            pid = str(row.get('paper_id', '') or '').strip()
            m = mapping.get(pid)
            if m:
                row.update(m)
            rows.append(row)
        index_path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')

    if graph_views_path.exists():
        views = json.loads(graph_views_path.read_text(encoding='utf-8'))
        paper_map = views.get('paper_map', {}) if isinstance(views, dict) else {}
        if isinstance(paper_map, dict):
            for _, v in paper_map.items():
                if not isinstance(v, dict):
                    continue
                pid = str(v.get('paper_id', '') or '').strip()
                m = mapping.get(pid)
                if m:
                    v['title'] = m['title']
                    v['display_title'] = m['display_title']
                    v['source_md_path'] = m['source_md_path']
                    v['source_pdf_name'] = m['source_pdf_name']
                    v['offline_html_path'] = m['html_path']
        graph_views_path.write_text(json.dumps(views, ensure_ascii=False), encoding='utf-8')

    return {'updated_papers': updated, 'workspace': str(workspace)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="", help="Optional specific workspace path")
    args = ap.parse_args()

    targets: list[Path]
    if str(args.workspace or "").strip():
        targets = [Path(str(args.workspace).strip())]
    else:
        targets = [p for p in WORKSPACES_ROOT.glob("*") if p.is_dir()]

    results: list[dict] = []
    for ws in targets:
        try:
            results.append(repair_one_workspace(ws))
        except Exception as exc:
            results.append({'updated_papers': 0, 'workspace': str(ws), 'error': str(exc)})
    print(json.dumps({'workspaces': results}, ensure_ascii=False))


if __name__ == '__main__':
    main()
