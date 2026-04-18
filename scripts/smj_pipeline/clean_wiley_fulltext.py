from __future__ import annotations

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup
from ftfy import fix_text
from markdownify import markdownify as md


DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "svg",
    "canvas",
}

DROP_CLASS_TOKENS = [
    "cookie",
    "osano",
    "modal",
    "login",
    "register",
    "article-row-right",
    "article-tool",
    "coolbar",
    "figure-viewer",
    "qrcode",
    "advert",
    "ad-",
    "metrics",
    "altmetric",
    "citation-modal",
    "social",
    "toolbar",
    "share",
    "related",
    "widget",
]

KEEP_ATTRS = {"href", "src", "alt"}
BASE_URL = "https://sms.onlinelibrary.wiley.com"

# Common mojibake seen in Wiley page dumps rendered with mixed encodings.
MOJIBAKE_MAP = {
    "聽": " ",
    "鈥�": "'",
    "鈥檚": "'s",
    "鈥淲": "\"W",
    "鈥淚": "\"I",
    "鈥渋": "\"i",
    "鈥渉": "\"h",
    "鈥渢": "\"t",
    "鈥?": "\"",
    "鈥" : "-",
    "鈥攖": "—t",
    "鈥攕": "—s",
    "鈥攃": "—c",
    "鈥攙": "—v",
    "鈥攈": "—h",
    "鈥攁": "—a",
    "鈥攆": "—n",
    "鈥攂": "—b",
    "鈥攔": "—r",
    "鈥墆": "-y",
    "鈥塪": "-d",
    "鈥塵": "-m",
    "鈥?": "–",
    "Santal贸": "Santaló",
    "Santal庐": "Santaló",
    "&nbsp;": " ",
}

HARD_CHAR_MAP = {
    "\u9225\u6516": "—t",
    "\u9225\u6515": "—s",
    "\u9225\u6519": "—v",
    "\u9225\u6501": "—a",
    "\u9225\u650d": "—l",
    "\u9225\u6506": "—n",
    "\u9225\u6502": "—b",
    "\u9225\u6514": "—r",
    "\u9225\u5886": "–y",
    "\u9225\u586a": "–d",
    "\u9225\u5875": "–m",
    "\u9225": "—",
    "\u5e90": "ó",
    "\u8d38": "ó",
    "\u5886": "y",
    "\u586a": "d",
    "\u5875": "m",
    "\u6501": "a",
    "\u650d": "l",
    "\u63f5": "b",
    "\u7709": "e",
    "\u6506": "n",
    "\u6515": "s",
    "\u6519": "v",
    "\u6502": "b",
    "\u6514": "r",
    "\u81b0": "o",
    "\u8305": "é",
    "\u813f": "a",
    "\ue6c3": "-",
}


def find_article_container(soup: BeautifulSoup):
    for selector in [".article__body", ".article__content", "article", "main"]:
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) > 5000:
            return node
    return soup.body or soup


def should_drop_by_class(tag) -> bool:
    if tag.find_parent("table") is not None:
        return False
    attrs = getattr(tag, "attrs", None) or {}
    classes = attrs.get("class") or []
    for cls in classes:
        lower = cls.lower()
        if any(token in lower for token in DROP_CLASS_TOKENS):
            return True
    return False


def normalize_mojibake(text: str) -> str:
    out = text
    for _ in range(3):
        fixed = fix_text(out)
        if fixed == out:
            break
        out = fixed
    for bad, good in MOJIBAKE_MAP.items():
        out = out.replace(bad, good)
    out = re.sub(r"(\d)鈥\?(\d)", r"\1–\2", out)
    out = re.sub(r"(\d)鈥(\d)", r"\1–\2", out)
    out = out.replace("鈥", "—")
    out = out.replace("庐", "ó")
    out = out.replace("贸", "ó")
    return out


def hard_cleanup(text: str) -> str:
    out = text
    for bad, good in HARD_CHAR_MAP.items():
        out = out.replace(bad, good)
    return out


def sanitize_container(container: BeautifulSoup):
    for tag_name in DROP_TAGS:
        for node in container.find_all(tag_name):
            node.decompose()

    for node in container.find_all(True):
        if node.name == "table" or node.find_parent("table") is not None:
            # Keep table subtree exactly as-is.
            continue
        if should_drop_by_class(node):
            node.decompose()
            continue
        attrs = getattr(node, "attrs", None) or {}
        for attr in list(attrs.keys()):
            if attr not in KEEP_ATTRS:
                del node.attrs[attr]

    for node in container.find_all(string=True):
        if node.find_parent("table") is not None:
            continue
        t = str(node).strip().lower()
        if t in {
            "view metrics",
            "download pdf",
            "open access",
            "search for more papers by this author",
        }:
            node.extract()

    return container


def simplify_media(container: BeautifulSoup) -> None:
    for picture in container.find_all("picture"):
        if picture.find_parent("table") is not None:
            continue
        img = picture.find("img")
        if img:
            picture.replace_with(img)
        else:
            picture.unwrap()
    for source in container.find_all("source"):
        if source.find_parent("table") is not None:
            continue
        source.decompose()


def absolutize_links(container: BeautifulSoup) -> None:
    for a in container.find_all("a"):
        if a.find_parent("table") is not None:
            continue
        href = (a.get("href") or "").strip()
        if href.startswith("/"):
            a["href"] = BASE_URL + href
    for img in container.find_all("img"):
        if img.find_parent("table") is not None:
            continue
        src = (img.get("src") or "").strip()
        if src.startswith("/"):
            img["src"] = BASE_URL + src


def clean_text_nodes(container: BeautifulSoup) -> None:
    for node in container.find_all(string=True):
        if node.find_parent("table") is not None:
            continue
        old = str(node)
        new = normalize_mojibake(old)
        if new != old:
            node.replace_with(new)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = normalize_mojibake(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    lines = [x.rstrip() for x in text.strip().splitlines()]
    cleaned: list[str] = []
    prev = None
    noise_exact = {
        "Search for more papers by this author",
        "view metrics",
        "PDF",
        "Open Access",
    }
    for line in lines:
        if not line:
            if prev != "":
                cleaned.append("")
                prev = ""
            continue
        if line in noise_exact:
            continue
        if line == prev:
            continue
        cleaned.append(line)
        prev = line
    return "\n".join(cleaned).strip()


def structure_report(meta: dict[str, str], article_node: BeautifulSoup) -> str:
    tag_counts: dict[str, int] = {}
    for node in article_node.find_all(True):
        tag_counts[node.name] = tag_counts.get(node.name, 0) + 1
    top = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    headings = []
    for h in article_node.find_all(["h2", "h3", "h4"]):
        text = normalize_text(h.get_text(" ", strip=True))
        if text:
            headings.append(text)

    lines = []
    lines.append(f"# HTML Structure Report: {meta['doi'] or 'unknown-doi'}")
    lines.append("")
    lines.append(f"- Title: {normalize_text(meta['title'])}")
    lines.append(f"- Journal: {meta['journal']}")
    lines.append(f"- Volume/Issue: {meta['volume_issue']}")
    lines.append(f"- Pages: {meta['pages']}")
    lines.append(f"- Article text length: {len(article_node.get_text(' ', strip=True))}")
    lines.append("")
    lines.append("## Tag Counts (Top 20)")
    lines.append("")
    for tag, cnt in top:
        lines.append(f"- `{tag}`: {cnt}")
    lines.append("")
    lines.append("## Headings (First 40)")
    lines.append("")
    for h in headings[:40]:
        lines.append(f"- {h}")
    lines.append("")
    return "\n".join(lines)


def build_markdown(meta: dict[str, str], article_html: str) -> str:
    head = []
    head.append(f"# {normalize_text(meta['title'])}")
    head.append("")
    head.append(f"- Journal: {meta['journal']}")
    head.append(f"- DOI: {meta['doi']}")
    head.append(f"- Volume/Issue: {meta['volume_issue']}")
    head.append(f"- Pages: {meta['pages']}")
    head.append("")

    parsed = BeautifulSoup(article_html, "lxml")
    table_map: dict[str, str] = {}
    for idx, table in enumerate(parsed.find_all("table"), start=1):
        placeholder = f"__RAW_TABLE_{idx}__"
        table_map[placeholder] = str(table)
        table.replace_with(parsed.new_string(placeholder))

    body_md = md(
        str(parsed),
        heading_style="ATX",
        bullets="-",
        escape_asterisks=False,
        escape_underscores=False,
    )
    body_md = normalize_text(body_md)
    for placeholder, raw_table in table_map.items():
        body_md = body_md.replace(placeholder, f"\n\n{raw_table}\n\n")

    return hard_cleanup("\n".join(head) + body_md + "\n")


def build_offline_html(meta: dict[str, str], article_html: str) -> str:
    style = """
body { font-family: Georgia, \"Times New Roman\", serif; line-height: 1.6; margin: 2rem auto; max-width: 900px; padding: 0 1rem; color: #1f2937; background: #ffffff; }
h1, h2, h3, h4 { line-height: 1.25; margin-top: 1.4em; }
h1 { font-size: 2rem; margin-top: 0.2em; }
h2 { font-size: 1.4rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.2em; }
p, li { font-size: 1.02rem; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.95rem; }
th, td { border: 1px solid #d1d5db; padding: 0.4em 0.55em; vertical-align: top; }
figure { margin: 1.2em 0; }
figcaption { color: #374151; font-size: 0.92rem; }
.meta { color: #4b5563; font-size: 0.95rem; margin-bottom: 1.1rem; }
img { max-width: 100%; height: auto; }
a { color: #1d4ed8; text-decoration: none; }
a:hover { text-decoration: underline; }
"""
    meta_html = f"""
<h1>{normalize_text(meta['title'])}</h1>
<div class=\"meta\">
  <div><strong>Journal:</strong> {meta['journal']}</div>
  <div><strong>DOI:</strong> {meta['doi']}</div>
  <div><strong>Volume/Issue:</strong> {meta['volume_issue']} | <strong>Pages:</strong> {meta['pages']}</div>
</div>
"""

    return hard_cleanup(f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{normalize_text(meta['title'])}</title>
  <style>{style}</style>
</head>
<body>
  {meta_html}
  {article_html}
</body>
</html>
""")


def run(args: argparse.Namespace) -> None:
    src = Path(args.input_html)
    out_md = Path(args.output_md)
    out_html = Path(args.output_offline_html)
    out_report = Path(args.output_structure_report)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_report.parent.mkdir(parents=True, exist_ok=True)

    soup = BeautifulSoup(src.read_text(encoding="utf-8", errors="ignore"), "lxml")

    meta = {
        "title": soup.title.get_text(" ", strip=True) if soup.title else "Article",
        "journal": (soup.find("meta", attrs={"name": "citation_journal_title"}) or {}).get("content", "").strip(),
        "doi": (soup.find("meta", attrs={"name": "citation_doi"}) or {}).get("content", "").strip(),
        "pages": "",
        "volume_issue": "",
    }
    first_page = (soup.find("meta", attrs={"name": "citation_firstpage"}) or {}).get("content", "").strip()
    last_page = (soup.find("meta", attrs={"name": "citation_lastpage"}) or {}).get("content", "").strip()
    vol = (soup.find("meta", attrs={"name": "citation_volume"}) or {}).get("content", "").strip()
    issue = (soup.find("meta", attrs={"name": "citation_issue"}) or {}).get("content", "").strip()
    meta["pages"] = f"{first_page}-{last_page}".strip("-")
    if vol and issue:
        meta["volume_issue"] = f"{vol}({issue})"
    elif vol:
        meta["volume_issue"] = vol
    else:
        meta["volume_issue"] = issue

    container = find_article_container(soup)
    cleaned = sanitize_container(container)
    simplify_media(cleaned)
    absolutize_links(cleaned)
    clean_text_nodes(cleaned)

    article_html = str(cleaned)
    markdown = build_markdown(meta, article_html)
    offline_html = build_offline_html(meta, article_html)
    report_md = hard_cleanup(structure_report(meta, cleaned))

    out_md.write_text(markdown, encoding="utf-8")
    out_html.write_text(offline_html, encoding="utf-8")
    out_report.write_text(report_md, encoding="utf-8")

    print(f"Wrote markdown: {out_md}")
    print(f"Wrote offline html: {out_html}")
    print(f"Wrote structure report: {out_report}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean Wiley full-text HTML into structured Markdown + offline HTML.")
    parser.add_argument("--input-html", default="outputs/manual_3_wiley_text/smj_70040_full.html")
    parser.add_argument("--output-md", default="outputs/manual_3_wiley_text/smj_70040_structured.md")
    parser.add_argument("--output-offline-html", default="outputs/manual_3_wiley_text/smj_70040_offline.html")
    parser.add_argument("--output-structure-report", default="outputs/manual_3_wiley_text/smj_70040_structure_report.md")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
