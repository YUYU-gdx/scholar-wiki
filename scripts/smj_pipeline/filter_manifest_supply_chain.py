from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class MatchTerm:
    raw: str
    normalized: str
    is_cjk: bool
    pattern: re.Pattern[str] | None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Filter SMJ manifest by supply/chain lexicon against title+abstract+keywords."
    )
    p.add_argument(
        "--input-manifest",
        type=Path,
        default=Path("outputs/smj_extraction_mvp/manifest_from_success_nobom.jsonl"),
    )
    p.add_argument(
        "--lexicon",
        type=Path,
        default=Path("prompt/supply_chain_lexicon.md"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/smj_supply_chain_batch"),
    )
    p.add_argument(
        "--run-id",
        default="",
        help="Optional run id. Default: supply_chain_YYYYMMDD_HHMMSS (UTC).",
    )
    p.add_argument(
        "--preview-size",
        type=int,
        default=200,
        help="Rows written to hits_preview.csv",
    )
    return p.parse_args()


def _utc_run_id(prefix: str = "supply_chain") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}"


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            obj = json.loads(t)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _read_html(row: dict[str, Any], root: Path) -> str:
    direct = str(row.get("html", "") or "")
    if direct.strip():
        return direct
    for key in ("offline_html_path", "raw_html_path", "html_path", "full_html_path"):
        v = str(row.get(key, "") or "").strip()
        if not v:
            continue
        p = Path(v)
        if not p.is_absolute():
            p = root / p
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def _load_lexicon(path: Path) -> list[MatchTerm]:
    terms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        if t.startswith("-"):
            t = t[1:].strip()
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            terms.append(t)
    seen: set[str] = set()
    compiled: list[MatchTerm] = []
    for raw in terms:
        normalized = _norm(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        is_cjk = bool(re.search(r"[\u4e00-\u9fff]", raw))
        pattern: re.Pattern[str] | None = None
        if not is_cjk:
            token = re.escape(normalized)
            token = token.replace(r"\ ", r"[\s\-_]+")
            pattern = re.compile(rf"(?<![a-z0-9]){token}(?![a-z0-9])", re.IGNORECASE)
        compiled.append(MatchTerm(raw=raw, normalized=normalized, is_cjk=is_cjk, pattern=pattern))
    return compiled


def _norm(text: str) -> str:
    t = html.unescape(str(text or ""))
    t = t.lower()
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_meta(raw_html: str, name: str) -> list[str]:
    # name= and property= are both common in publisher pages.
    pattern = re.compile(
        rf'(?is)<meta\s+[^>]*(?:name|property)\s*=\s*["\']{re.escape(name)}["\'][^>]*content\s*=\s*["\']([^"\']+)["\']'
    )
    values: list[str] = []
    for m in pattern.finditer(raw_html):
        v = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
        if v:
            values.append(v)
    return values


def _extract_title_abstract_keywords(raw_html: str) -> tuple[str, str, str]:
    titles = _extract_meta(raw_html, "citation_title")
    if not titles:
        titles = _extract_meta(raw_html, "dc.title")
    if not titles:
        titles = _extract_meta(raw_html, "og:title")

    abstracts = _extract_meta(raw_html, "citation_abstract")
    if not abstracts:
        abstracts = _extract_meta(raw_html, "dc.description")
    if not abstracts:
        abstracts = _extract_meta(raw_html, "description")

    keywords_meta = _extract_meta(raw_html, "citation_keywords")
    keywords: list[str] = []
    for item in keywords_meta:
        parts = [p.strip() for p in re.split(r"[;,|]", item) if p.strip()]
        if parts:
            keywords.extend(parts)
        else:
            keywords.append(item)
    # Keep dedup stable.
    kw_out: list[str] = []
    seen: set[str] = set()
    for k in keywords:
        nk = _norm(k)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        kw_out.append(k)
    if not titles:
        m_title = re.search(r"(?is)<title>(.*?)</title>", raw_html)
        if m_title:
            titles = [re.sub(r"\s+", " ", html.unescape(m_title.group(1))).strip()]
    if not titles:
        m_h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", raw_html)
        if m_h1:
            h1_text = re.sub(r"(?is)<[^>]+>", " ", m_h1.group(1))
            h1_text = re.sub(r"\s+", " ", html.unescape(h1_text)).strip()
            if h1_text:
                titles = [h1_text]

    if not abstracts:
        line_abstract = _extract_abstract_from_lines(raw_html)
        if line_abstract:
            abstracts = [line_abstract]

    if not kw_out:
        kw_out = _extract_keywords_from_lines(raw_html)

    return (" ".join(titles).strip(), " ".join(abstracts).strip(), "; ".join(kw_out).strip())


def _html_to_lines(raw_html: str) -> list[str]:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    text = re.sub(
        r"(?is)</(p|div|section|article|li|ul|ol|table|tr|thead|tbody|tfoot|h1|h2|h3|h4|h5|h6|br)>",
        "\n",
        text,
    )
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in text.splitlines()]
    return [x for x in lines if x]


def _extract_abstract_from_lines(raw_html: str) -> str:
    lines = _html_to_lines(raw_html)
    if not lines:
        return ""
    start = -1
    for i, line in enumerate(lines):
        if line.lower() == "abstract":
            start = i + 1
            break
    if start < 0:
        return ""
    stop_markers = (
        "keywords",
        "key words",
        "citing literature",
        "references",
        "introduction",
        "supporting information",
    )
    collected: list[str] = []
    for line in lines[start:]:
        probe = line.lower().strip()
        if not probe:
            if len(collected) >= 2:
                break
            continue
        if any(probe.startswith(m) for m in stop_markers):
            break
        if re.match(r"^\d+(\.\d+)?\s+[A-Z][A-Z\s\-]{2,}$", line):
            break
        collected.append(line)
        if len(" ".join(collected)) > 3000:
            break
    return re.sub(r"\s+", " ", " ".join(collected)).strip()


def _extract_keywords_from_lines(raw_html: str) -> list[str]:
    lines = _html_to_lines(raw_html)
    out: list[str] = []
    for line in lines:
        low = line.lower()
        if not (low.startswith("keywords") or low.startswith("key words")):
            continue
        text = re.sub(r"(?i)^key\s*words?\s*[:：]?\s*", "", line).strip()
        if not text:
            continue
        out.extend([x.strip() for x in re.split(r"[;,|]", text) if x.strip()])
    dedup: list[str] = []
    seen: set[str] = set()
    for k in out:
        nk = _norm(k)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        dedup.append(k)
    return dedup


def _match_terms(title: str, abstract: str, keywords: str, terms: list[MatchTerm]) -> list[str]:
    text_en = _norm(" ".join([title, abstract, keywords]))
    text_raw = f"{title}\n{abstract}\n{keywords}"
    hits: list[str] = []
    for t in terms:
        if t.is_cjk:
            if t.raw in text_raw:
                hits.append(t.raw)
            continue
        if t.pattern and t.pattern.search(text_en):
            hits.append(t.raw)
    return hits


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")


def main() -> None:
    args = parse_args()
    if not args.input_manifest.exists():
        raise RuntimeError(f"input manifest not found: {args.input_manifest}")
    if not args.lexicon.exists():
        raise RuntimeError(f"lexicon not found: {args.lexicon}")

    root = Path.cwd()
    run_id = args.run_id.strip() or _utc_run_id()
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    terms = _load_lexicon(args.lexicon)
    rows = _iter_jsonl(args.input_manifest)
    matched_rows: list[dict[str, Any]] = []
    preview_rows: list[dict[str, str]] = []
    term_counter: dict[str, int] = {}

    total = len(rows)
    html_missing = 0
    no_fields = 0

    for row in rows:
        html_text = _read_html(row, root)
        if not html_text.strip():
            html_missing += 1
            continue
        title, abstract, keywords = _extract_title_abstract_keywords(html_text)
        if not (title or abstract or keywords):
            no_fields += 1
            continue
        hits = _match_terms(title, abstract, keywords, terms)
        if not hits:
            continue
        for h in hits:
            term_counter[h] = term_counter.get(h, 0) + 1

        payload = dict(row)
        payload["keyword_filter_scope"] = "title+abstract+citation_keywords"
        payload["keyword_filter_hits"] = hits
        payload["keyword_filter_title"] = title
        payload["keyword_filter_keywords"] = keywords
        matched_rows.append(payload)

        if len(preview_rows) < max(0, int(args.preview_size)):
            preview_rows.append(
                {
                    "paper_id": str(row.get("paper_id", "") or ""),
                    "doi": str(row.get("doi", "") or ""),
                    "hit_terms": "; ".join(hits),
                    "title": title,
                    "keywords": keywords,
                }
            )

    out_manifest = run_dir / "manifest_input.jsonl"
    _write_jsonl(out_manifest, matched_rows)

    preview_csv = run_dir / "hits_preview.csv"
    with preview_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["paper_id", "doi", "hit_terms", "title", "keywords"])
        writer.writeheader()
        writer.writerows(preview_rows)

    top_terms = sorted(term_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:80]
    report = {
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_manifest": str(args.input_manifest),
        "lexicon_path": str(args.lexicon),
        "scope": "title+abstract+citation_keywords",
        "input_total": total,
        "matched_total": len(matched_rows),
        "html_missing": html_missing,
        "no_title_abstract_keywords": no_fields,
        "term_count": len(terms),
        "top_terms": [{"term": k, "hits": v} for k, v in top_terms],
        "manifest_output": str(out_manifest),
        "preview_csv": str(preview_csv),
    }
    (run_dir / "filter_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
