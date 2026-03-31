from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scrapling.fetchers import Fetcher, StealthyFetcher
except Exception:  # pragma: no cover - fallback for unit-test environments without scrapling
    Fetcher = None  # type: ignore[assignment]
    StealthyFetcher = None  # type: ignore[assignment]


SMJ_ISSN = "1097-0266"
MANIFEST_FIELDS = [
    "doi",
    "title",
    "pub_date",
    "article_url",
    "raw_html_path",
    "offline_html_path",
    "structured_md_path",
    "structure_report_path",
    "pdf_path",
    "html_ok",
    "pdf_ok",
    "final_status",
    "fail_reason",
    "updated_at",
]


@dataclass
class SmjWork:
    doi: str
    title: str
    pub_date: str
    article_url: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_doi(doi: str) -> str:
    return doi.strip().lower()


def shard_for_doi(doi: str, workers: int) -> int:
    if workers <= 0:
        raise ValueError("workers must be >= 1")
    digest = hashlib.md5(normalize_doi(doi).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % workers


def safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in {"-", "_", "."} else "_" for c in text).strip("_")


def is_pdf_bytes(data: bytes, content_type: str) -> bool:
    ctype = (content_type or "").lower()
    return "pdf" in ctype or data.startswith(b"%PDF")


def pick_date(item: dict[str, Any]) -> str:
    keys = ["published-print", "published-online", "issued", "created"]
    for key in keys:
        node = item.get(key) or {}
        parts = (node.get("date-parts") or [[None]])[0]
        if not parts:
            continue
        y = parts[0] if len(parts) > 0 else None
        m = parts[1] if len(parts) > 1 else 1
        d = parts[2] if len(parts) > 2 else 1
        if y:
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return ""


def crossref_smj_works(years: int, count: int, all_history: bool) -> list[SmjWork]:
    current_year = datetime.now(timezone.utc).year
    if not all_history:
        start_year = current_year - years + 1
        start = f"{start_year:04d}-01-01"
        end = f"{current_year:04d}-12-31"
        rows = max(200, count * 10)
        params = {
            "filter": f"from-pub-date:{start},until-pub-date:{end},type:journal-article",
            "sort": "published",
            "order": "desc",
            "rows": str(rows),
        }
        url = (
            f"https://api.crossref.org/journals/{SMJ_ISSN}/works?"
            + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "smj-all-runner/0.2"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        items = (payload.get("message") or {}).get("items") or []
        out: list[SmjWork] = []
        seen: set[str] = set()
        for item in items:
            doi = normalize_doi(str(item.get("DOI") or ""))
            if not doi or doi in seen:
                continue
            seen.add(doi)
            title = ((item.get("title") or [""])[0] or "").strip()
            pub_date = pick_date(item)
            out.append(
                SmjWork(
                    doi=doi,
                    title=title or doi,
                    pub_date=pub_date,
                    article_url=f"https://sms.onlinelibrary.wiley.com/doi/full/{doi}",
                )
            )
            if len(out) >= count:
                break
        return out

    # Crossref cursor pagination for this source is unreliable beyond ~2000 items.
    # Build all-history list by yearly windows to ensure complete coverage.
    seen: set[str] = set()
    out: list[SmjWork] = []
    year_start = 1950
    year_end = current_year
    for y in range(year_start, year_end + 1):
        params = {
            "filter": f"issn:{SMJ_ISSN},type:journal-article,from-pub-date:{y}-01-01,until-pub-date:{y}-12-31",
            "rows": "1000",
        }
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, headers={"User-Agent": "smj-all-runner/0.2"})
        payload: dict[str, Any] | None = None
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 5:
                    time.sleep(2**attempt)
                    continue
                raise
        if payload is None:
            continue
        items = (payload.get("message") or {}).get("items") or []
        for item in items:
            doi = normalize_doi(str(item.get("DOI") or ""))
            if not doi or doi in seen:
                continue
            seen.add(doi)
            title = ((item.get("title") or [""])[0] or "").strip()
            pub_date = pick_date(item)
            out.append(
                SmjWork(
                    doi=doi,
                    title=title or doi,
                    pub_date=pub_date,
                    article_url=f"https://sms.onlinelibrary.wiley.com/doi/full/{doi}",
                )
            )
    return out


def load_works_from_csv(path: Path) -> list[SmjWork]:
    rows: list[SmjWork] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            doi = normalize_doi(row.get("doi", ""))
            if not doi:
                continue
            title = (row.get("title") or "").strip() or doi
            pub_date = (row.get("pub_date") or "").strip()
            article_url = (row.get("article_url") or "").strip()
            if not article_url:
                article_url = f"https://sms.onlinelibrary.wiley.com/doi/full/{doi}"
            rows.append(
                SmjWork(
                    doi=doi,
                    title=title,
                    pub_date=pub_date,
                    article_url=article_url,
                )
            )
    return rows


def save_works_csv(path: Path, works: list[SmjWork]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["doi", "title", "pub_date", "article_url"])
        writer.writeheader()
        for w in works:
            writer.writerow(
                {
                    "doi": w.doi,
                    "title": w.title,
                    "pub_date": w.pub_date,
                    "article_url": w.article_url,
                }
            )


def wiley_pdf_candidates(doi: str) -> list[str]:
    return [
        f"https://sms.onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true",
        f"https://sms.onlinelibrary.wiley.com/doi/pdf/{doi}",
        f"https://sms.onlinelibrary.wiley.com/doi/epdf/{doi}",
    ]


def load_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            doi = normalize_doi(row.get("doi", ""))
            if doi:
                out[doi] = row
    return out


def save_manifest(path: Path, rows: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for doi in sorted(rows.keys()):
            writer.writerow(rows[doi])


def update_summary(path: Path, rows: dict[str, dict[str, str]]) -> None:
    by_status: dict[str, int] = {}
    for row in rows.values():
        key = row.get("final_status", "")
        by_status[key] = by_status.get(key, 0) + 1
    payload = {
        "generated_at": now_iso(),
        "total": len(rows),
        "by_status": by_status,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cleaner(input_html: Path, output_md: Path, output_offline_html: Path, output_report: Path) -> None:
    cmd = [
        sys.executable,
        "scripts/clean_wiley_fulltext.py",
        "--input-html",
        str(input_html),
        "--output-md",
        str(output_md),
        "--output-offline-html",
        str(output_offline_html),
        "--output-structure-report",
        str(output_report),
    ]
    subprocess.run(cmd, check=True)


def run(args: argparse.Namespace) -> None:
    if args.workers < 1:
        raise ValueError("--workers must be >= 1")
    if args.worker_index < 0 or args.worker_index >= args.workers:
        raise ValueError("--worker-index must satisfy 0 <= worker-index < workers")

    out_dir = Path(args.output_dir)
    raw_dir = out_dir / "raw"
    clean_dir = out_dir / "clean"
    pdf_dir = out_dir / "pdf"
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    manifest_csv = out_dir / "manifest.csv"
    summary_json = out_dir / "summary.json"
    if args.input_csv:
        works = load_works_from_csv(Path(args.input_csv))
    else:
        works = crossref_smj_works(args.years, args.count, all_history=args.all_history)
    if not works:
        raise RuntimeError("No SMJ works returned from Crossref for requested range.")
    if args.max_items > 0:
        works = works[: args.max_items]
    if args.save_works_csv:
        save_works_csv(Path(args.save_works_csv), works)
        print(f"Saved works csv: {args.save_works_csv} ({len(works)} rows)")
        if args.only_build_input:
            return
    works = [w for w in works if shard_for_doi(w.doi, args.workers) == args.worker_index]

    existing = load_manifest(manifest_csv)
    rows: dict[str, dict[str, str]] = {}

    for w in works:
        slug = safe_name(w.doi.replace("/", "_"))
        raw_html = raw_dir / f"{slug}_full.html"
        offline_html = clean_dir / f"{slug}_offline.html"
        structured_md = clean_dir / f"{slug}_structured.md"
        structure_report = clean_dir / f"{slug}_structure_report.md"
        pdf_path = pdf_dir / f"{slug}.pdf"

        row = existing.get(w.doi, {})
        if row.get("final_status") == "success" and args.resume:
            rows[w.doi] = row
            continue

        row = {
            "doi": w.doi,
            "title": w.title,
            "pub_date": w.pub_date,
            "article_url": w.article_url,
            "raw_html_path": str(raw_html),
            "offline_html_path": str(offline_html),
            "structured_md_path": str(structured_md),
            "structure_report_path": str(structure_report),
            "pdf_path": str(pdf_path),
            "html_ok": "false",
            "pdf_ok": "false",
            "final_status": "running",
            "fail_reason": "",
            "updated_at": now_iso(),
        }
        rows[w.doi] = row
        save_manifest(manifest_csv, rows)

        try:
            page = StealthyFetcher.fetch(
                w.article_url,
                headless=False if args.no_headless else True,
                solve_cloudflare=True,
                network_idle=True,
                timeout=args.timeout_ms,
                real_chrome=True,
            )
            body = getattr(page, "body", b"") or b""
            if isinstance(body, str):
                body = body.encode("utf-8", errors="ignore")
            raw_html.write_bytes(body)
            run_cleaner(raw_html, structured_md, offline_html, structure_report)
            row["html_ok"] = "true"
        except Exception as exc:
            row["final_status"] = "failed"
            row["fail_reason"] = f"html_pipeline_error:{type(exc).__name__}"
            row["updated_at"] = now_iso()
            rows[w.doi] = row
            save_manifest(manifest_csv, rows)
            continue

        pdf_ok = False
        for candidate in wiley_pdf_candidates(w.doi):
            try:
                resp = Fetcher.get(candidate, stealthy_headers=True, follow_redirects=True)
            except Exception:
                continue
            data = getattr(resp, "body", b"") or b""
            if isinstance(data, str):
                data = data.encode("utf-8", errors="ignore")
            headers = getattr(resp, "headers", {}) or {}
            ctype = ""
            for k, v in headers.items():
                if str(k).lower() == "content-type":
                    ctype = str(v)
                    break
            if is_pdf_bytes(data, ctype) and len(data) >= args.min_pdf_bytes:
                pdf_path.write_bytes(data)
                pdf_ok = True
                break

        row["pdf_ok"] = "true" if pdf_ok else "false"
        if row["html_ok"] == "true" and row["pdf_ok"] == "true":
            row["final_status"] = "success"
            row["fail_reason"] = ""
        else:
            row["final_status"] = "failed"
            row["fail_reason"] = "pdf_missing_or_blocked"
        row["updated_at"] = now_iso()
        rows[w.doi] = row
        save_manifest(manifest_csv, rows)

    update_summary(summary_json, rows)
    print(f"Saved manifest: {manifest_csv}")
    print(f"Saved summary: {summary_json}")
    print(f"Worker: index={args.worker_index}/{args.workers}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch latest SMJ papers from recent years and save cleaned HTML + PDF artifacts."
    )
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--all-history", action="store_true", help="Ignore year/count window and fetch all SMJ articles.")
    parser.add_argument("--input-csv", default="", help="Optional CSV with columns: doi,title,pub_date,article_url")
    parser.add_argument("--max-items", type=int, default=0, help="Process at most N DOIs this run (0 = no limit).")
    parser.add_argument("--output-dir", default="outputs/smj_recent10_run")
    parser.add_argument("--timeout-ms", type=int, default=180000)
    parser.add_argument("--min-pdf-bytes", type=int, default=4096)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--no-headless", action="store_true", default=True)
    parser.add_argument("--headless", dest="no_headless", action="store_false")
    parser.add_argument("--workers", type=int, default=1, help="Total shard count for parallel runs.")
    parser.add_argument("--worker-index", type=int, default=0, help="Current shard index [0, workers).")
    parser.add_argument("--save-works-csv", default="", help="Optional output CSV for discovered DOI works list.")
    parser.add_argument(
        "--only-build-input",
        action="store_true",
        help="Build/save works CSV and exit without fetching article content.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
