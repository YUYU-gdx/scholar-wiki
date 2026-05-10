from __future__ import annotations

from dataclasses import dataclass
import html
import re


_SECTION_BLOCK_RE = re.compile(r"<section\b[^>]*>.*?</section>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr\b[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_CAPTION_RE = re.compile(r"<caption\b[^>]*>(.*?)</caption>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_HYPOTHESES_RE = re.compile(r"\bhypotheses?\b", re.IGNORECASE)
_RESULTS_RE = re.compile(r"\bresults?\b", re.IGNORECASE)
_ABSTRACT_RE = re.compile(r"\babstract\b", re.IGNORECASE)
_REFERENCES_RE = re.compile(r"\breferences?\b", re.IGNORECASE)
_MAIN_MODEL_RE = re.compile(r"\bmain[-\s]?model\b", re.IGNORECASE)
_STAT_SIGNAL_RE = re.compile(
    r"(\b(beta|coef|coefficient|odds ratio|hazard ratio|hr|or|b)\b\s*[:=]?\s*[-+]?\d"
    r"|p\s*[<=>]\s*0?\.\d+"
    r"|[tT]\s*[:=]?\s*[-+]?\d"
    r"|[zZ]\s*[:=]?\s*[-+]?\d)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class EvidenceSpan:
    kind: str
    start: int
    end: int
    text: str
    section_title: str | None = None


def locate_main_model_evidence(html: str) -> list[EvidenceSpan]:
    spans: list[EvidenceSpan] = []

    section_blocks = list(_SECTION_BLOCK_RE.finditer(html))
    if section_blocks:
        for block_match in section_blocks:
            block_html = block_match.group(0)
            title = _extract_title(block_html)
            title_norm = _normalize_text(title)
            if _is_ignored_section(title_norm):
                continue

            block_start = block_match.start()
            if _HYPOTHESES_RE.search(title_norm):
                spans.append(
                    EvidenceSpan(
                        kind="hypotheses",
                        start=block_start,
                        end=block_match.end(),
                        text=_clean_html(block_html),
                        section_title=title_norm,
                    )
                )
            elif _RESULTS_RE.search(title_norm):
                spans.append(
                    EvidenceSpan(
                        kind="results",
                        start=block_start,
                        end=block_match.end(),
                        text=_clean_html(block_html),
                        section_title=title_norm,
                    )
                )

            spans.extend(_locate_tables(block_html, block_start))
    else:
        spans.extend(_locate_tables(html, 0))

    spans.sort(key=lambda span: (span.start, span.end, span.kind))
    return spans


def _locate_tables(html: str, offset: int) -> list[EvidenceSpan]:
    spans: list[EvidenceSpan] = []
    for table_match in _TABLE_RE.finditer(html):
        table_html = table_match.group(0)
        if not _table_looks_relevant(table_html):
            continue

        table_start = offset + table_match.start()
        table_end = offset + table_match.end()
        spans.append(
            EvidenceSpan(
                kind="main_model_table",
                start=table_start,
                end=table_end,
                text=_clean_html(table_html),
            )
        )
        spans.extend(_locate_stat_rows(table_html, table_start))
    return spans


def _locate_stat_rows(table_html: str, offset: int) -> list[EvidenceSpan]:
    spans: list[EvidenceSpan] = []
    for row_match in _ROW_RE.finditer(table_html):
        row_html = row_match.group(0)
        if not _row_has_stat_signal(row_html):
            continue
        spans.append(
            EvidenceSpan(
                kind="main_model_stat",
                start=offset + row_match.start(),
                end=offset + row_match.end(),
                text=_clean_html(row_html),
            )
        )
    return spans


def _table_looks_relevant(table_html: str) -> bool:
    cleaned = _clean_html(table_html)
    return bool(_MAIN_MODEL_RE.search(cleaned) or _STAT_SIGNAL_RE.search(cleaned))


def _row_has_stat_signal(row_html: str) -> bool:
    cleaned = _clean_html(row_html)
    return bool(_MAIN_MODEL_RE.search(cleaned) or _STAT_SIGNAL_RE.search(cleaned))


def _extract_title(block_html: str) -> str:
    title_match = _TITLE_RE.search(block_html)
    if title_match is not None:
        return _clean_html(title_match.group(1))

    caption_match = _CAPTION_RE.search(block_html)
    if caption_match is not None:
        return _clean_html(caption_match.group(1))

    return ""


def _is_ignored_section(title: str) -> bool:
    return bool(_ABSTRACT_RE.search(title) or _REFERENCES_RE.search(title))


def _clean_html(value: str) -> str:
    return _normalize_text(html.unescape(_TAG_RE.sub(" ", value)))


def _normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()
