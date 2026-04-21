from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


THEME_SEEDS: dict[str, list[str]] = {
    "supply_chain": [
        "supply chain",
        "supply network",
        "supplier",
        "procurement",
        "sourcing",
        "logistics",
        "inventory",
        "resilience",
        "bullwhip",
        "\u4f9b\u5e94\u94fe",
        "\u4f9b\u5e94\u7f51\u7edc",
        "\u4f9b\u5e94\u5546",
        "\u91c7\u8d2d",
        "\u7269\u6d41",
        "\u5e93\u5b58",
        "\u97e7\u6027",
        "\u4f9b\u5e94\u4e2d\u65ad",
    ],
    "digitalization": [
        "digital",
        "digital transformation",
        "digitization",
        "digitalization",
        "digital capability",
        "digital platform",
        "information technology",
        "it capability",
        "it infrastructure",
        "e-commerce",
        "platform ecosystem",
        "big data",
        "data analytics",
        "industry 4.0",
        "digital ecosystem",
        "internet",
        "\u6570\u5b57\u5316",
        "\u6570\u5b57\u5316\u8f6c\u578b",
        "\u6570\u667a\u5316",
        "\u6570\u5b57\u80fd\u529b",
        "\u4fe1\u606f\u6280\u672f",
        "\u4fe1\u606f\u7cfb\u7edf",
        "\u4e92\u8054\u7f51",
        "\u5e73\u53f0\u751f\u6001",
        "\u667a\u80fd\u5236\u9020",
        "\u5927\u6570\u636e",
        "\u6570\u636e\u5206\u6790",
        "\u5de5\u4e1a4.0",
        "\u6570\u5b57\u5e73\u53f0",
    ],
    "ai": [
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "neural network",
        "generative ai",
        "large language model",
        "llm",
        "computer vision",
        "\u81ea\u7136\u8bed\u8a00\u5904\u7406",
        "\u4eba\u5de5\u667a\u80fd",
        "\u673a\u5668\u5b66\u4e60",
        "\u6df1\u5ea6\u5b66\u4e60",
        "\u795e\u7ecf\u7f51\u7edc",
        "\u751f\u6210\u5f0f",
        "\u5927\u6a21\u578b",
        "\u667a\u80fd\u7b97\u6cd5",
        "\u7b97\u6cd5\u6a21\u578b",
    ],
}

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_EN_TOKEN_RE = re.compile(r"[a-z][a-z0-9\\-]{2,}")
_ZH_TOKEN_RE = re.compile(r"[\\u4e00-\\u9fff]{2,8}")
_MULTISPACE_RE = re.compile(r"\\s+")

_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "for",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "into",
    "between",
    "among",
    "using",
    "based",
    "study",
    "paper",
    "results",
    "table",
    "figure",
    "section",
    "model",
    "analysis",
    "data",
    "research",
    "we",
    "our",
    "\u6211\u4eec",
    "\u4ee5\u53ca",
    "\u7814\u7a76",
    "\u672c\u6587",
    "\u7ed3\u679c",
    "\u65b9\u6cd5",
    "\u6a21\u578b",
    "\u6570\u636e",
    "\u5206\u6790",
    "\u53d8\u91cf",
    "\u7406\u8bba",
    "\u5047\u8bbe",
    "\u5f71\u54cd",
}


@dataclass(slots=True)
class Doc:
    paper_id: str
    doi: str
    doc_class: str
    source_path: str
    normalized_html_path: str
    token_estimate: int
    text_sha256: str
    text: str


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, dict):
                yield obj


def _strip_html(raw_html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    text = _TAG_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text)
    return text.strip().lower()


def _tokenize(text: str) -> list[str]:
    out = _EN_TOKEN_RE.findall(text)
    out.extend(_ZH_TOKEN_RE.findall(text))
    return out


def _load_docs(input_jsonl: Path, min_tokens: int) -> list[Doc]:
    docs: list[Doc] = []
    root = Path.cwd()
    for row in _iter_jsonl(input_jsonl):
        token_estimate = int(row.get("token_estimate", 0) or 0)
        if token_estimate < min_tokens:
            continue
        html_path = str(row.get("normalized_html_path", "") or "").strip()
        if not html_path:
            continue
        p = Path(html_path)
        if not p.is_absolute():
            p = root / p
        if not p.exists():
            continue
        try:
            html_text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = _strip_html(html_text)
        if not text:
            continue
        docs.append(
            Doc(
                paper_id=str(row.get("paper_id", "") or ""),
                doi=str(row.get("doi", "") or ""),
                doc_class=str(row.get("doc_class", "") or ""),
                source_path=str(row.get("source_path", "") or ""),
                normalized_html_path=str(row.get("normalized_html_path", "") or ""),
                token_estimate=token_estimate,
                text_sha256=str(row.get("text_sha256", "") or ""),
                text=text,
            )
        )
    return docs


def _seed_hits(text: str, seeds: list[str]) -> list[str]:
    hits: list[str] = []
    for term in seeds:
        t = term.lower().strip()
        if not t:
            continue
        if t in text:
            hits.append(term)
    return hits


def _build_dictionary(docs: list[Doc], seeds: list[str], top_n: int) -> list[str]:
    counter: Counter[str] = Counter()
    for doc in docs:
        for token in _tokenize(doc.text):
            if len(token) < 2:
                continue
            if token in _STOPWORDS:
                continue
            counter[token] += 1
    expanded = [t for t, _ in counter.most_common(top_n)]
    merged: list[str] = []
    seen: set[str] = set()
    for term in list(seeds) + expanded:
        key = term.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(term)
    return merged


def _match_docs(docs: list[Doc], dictionary: list[str], seeds: list[str], min_hits: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seed_terms = [s.lower().strip() for s in seeds if str(s).strip()]
    for doc in docs:
        if not any(st in doc.text for st in seed_terms):
            continue
        hits: list[str] = []
        for term in dictionary:
            t = term.lower().strip()
            if t and t in doc.text:
                hits.append(term)
        uniq_hits = sorted(set(hits), key=lambda x: (len(x), x), reverse=True)
        if len(uniq_hits) < min_hits:
            continue
        out.append(
            {
                "paper_id": doc.paper_id,
                "doi": doc.doi,
                "doc_class": doc.doc_class,
                "source_path": doc.source_path,
                "normalized_html_path": doc.normalized_html_path,
                "token_estimate": doc.token_estimate,
                "text_sha256": doc.text_sha256,
                "hit_terms": uniq_hits,
                "hit_count": len(uniq_hits),
            }
        )
    out.sort(key=lambda x: (-int(x["hit_count"]), str(x["paper_id"])))
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def _build_index_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "paper_id": str(row.get("paper_id", "") or ""),
                "doi": str(row.get("doi", "") or ""),
                "doc_class": str(row.get("doc_class", "") or ""),
                "hit_count": int(row.get("hit_count", 0) or 0),
                "hit_terms_preview": list(row.get("hit_terms", [])[:12]),
                "token_estimate": int(row.get("token_estimate", 0) or 0),
                "normalized_html_path": str(row.get("normalized_html_path", "") or ""),
                "source_path": str(row.get("source_path", "") or ""),
                "text_sha256": str(row.get("text_sha256", "") or ""),
            }
        )
    out.sort(key=lambda x: (-int(x["hit_count"]), x["paper_id"]))
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build theme dictionaries and theme datasets with lightweight indexes.")
    p.add_argument(
        "--input-jsonl",
        type=Path,
        default=Path("outputs/literature_base/class_abc/base_dataset_classified_all.jsonl"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/literature_base/theme_datasets"),
    )
    p.add_argument("--min-tokens", type=int, default=200)
    p.add_argument("--min-hits", type=int, default=2)
    p.add_argument("--top-terms", type=int, default=120)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    docs = _load_docs(args.input_jsonl, min_tokens=args.min_tokens)
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "input_jsonl": str(args.input_jsonl),
        "output_dir": str(out_dir),
        "doc_count_after_min_tokens": len(docs),
        "themes": {},
    }

    for theme, seeds in THEME_SEEDS.items():
        seeded_docs = [doc for doc in docs if _seed_hits(doc.text, seeds)]
        dictionary = _build_dictionary(seeded_docs, seeds=seeds, top_n=args.top_terms)
        matched = _match_docs(docs, dictionary=dictionary, seeds=seeds, min_hits=args.min_hits)
        index_rows = _build_index_rows(matched)

        theme_dir = out_dir / theme
        _write_json(theme_dir / "dictionary.json", {"theme": theme, "terms": dictionary})
        _write_jsonl(theme_dir / "matched_articles.jsonl", matched)
        _write_jsonl(theme_dir / "index.jsonl", index_rows)

        summary["themes"][theme] = {
            "seed_terms": len(seeds),
            "dictionary_terms": len(dictionary),
            "seeded_doc_count": len(seeded_docs),
            "matched_doc_count": len(matched),
            "dictionary_path": str(theme_dir / "dictionary.json"),
            "matched_articles_path": str(theme_dir / "matched_articles.jsonl"),
            "index_path": str(theme_dir / "index.jsonl"),
        }

    _write_json(out_dir / "theme_build_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
