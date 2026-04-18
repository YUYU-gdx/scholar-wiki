from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Iterable


_PROMPT_ROOT = Path(__file__).resolve().parents[3] / "prompt"
_SYSTEM_PROMPT_PATH = _PROMPT_ROOT / "extraction_system_prompt.md"
_REFERENCE_HEADINGS = (
    "references",
    "reference",
    "bibliography",
    "works cited",
    "cited references",
    "literature cited",
    "参考文献",
)


def load_system_prompt_template() -> str:
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_extraction_messages(document_html: str) -> tuple[str, str]:
    system_prompt = load_system_prompt_template()
    user_content = build_user_content(document_html)
    return system_prompt, user_content


def build_user_content(document_html: str) -> str:
    text = _html_to_text(document_html)
    return _truncate_before_references(text)


def extract_domain_tags_from_html(raw_html: str) -> list[str]:
    source = str(raw_html or "")
    if not source.strip():
        return []

    labels: list[str] = []
    # Wiley citation keywords.
    for m in re.finditer(r'(?is)<meta\s+name="citation_keywords"\s+content="([^"]+)"', source):
        value = _clean_label(m.group(1))
        if value:
            labels.append(value)

    # Wiley Adobe data layer topics (global subject codes).
    for m in re.finditer(
        r'(?is)\{"taxonomyUri":"global-subject-codes","topicLabel":"([^"]+)"',
        source,
    ):
        value = _clean_label(_decode_js_escaped(m.group(1)))
        if value:
            labels.append(value)

    return _dedupe(labels)


def _html_to_text(raw_html: str) -> str:
    source = str(raw_html or "")
    if not source.strip():
        return ""

    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", source)
    text = re.sub(r"(?is)<br\\s*/?>", "\n", text)
    text = re.sub(
        r"(?is)</(p|div|section|article|li|ul|ol|table|tr|thead|tbody|tfoot|h1|h2|h3|h4|h5|h6)>",
        "\n",
        text,
    )
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _truncate_before_references(text: str) -> str:
    if not text:
        return text

    lines = text.splitlines()
    cut_idx = len(lines)
    for idx, line in enumerate(lines):
        probe = _normalize_heading(line)
        if len(probe) > 80:
            continue
        if any(probe == h or probe.startswith(f"{h} ") for h in _REFERENCE_HEADINGS):
            cut_idx = idx
            break
    return "\n".join(lines[:cut_idx]).strip()


def _normalize_heading(line: str) -> str:
    lowered = line.lower().strip()
    lowered = re.sub(r"^[\\d\\W_]+", "", lowered)
    lowered = re.sub(r"[\\W_]+", " ", lowered).strip()
    return lowered


def _clean_label(value: str) -> str:
    text = html.unescape(str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _decode_js_escaped(value: str) -> str:
    text = str(value or "")
    try:
        return bytes(text, "utf-8").decode("unicode_escape")
    except Exception:
        return text


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        key = v.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out
