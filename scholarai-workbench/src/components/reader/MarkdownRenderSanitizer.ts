const TRANSLATION_LABEL_RE = /class=["']translation-label["']/i;
const DETAILS_TAG_RE = /<\/?details\b[^>]*>/gi;
const SUMMARY_TAG_RE = /<\/?summary\b[^>]*>/gi;
const INDENTED_TABLE_OPEN_RE = /^(\s{4,})<table\b/i;
const TABLE_CLOSE_RE = /<\/table\s*>/i;

function escapeHtmlTag(tag: string): string {
  return tag.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeDetailsAndSummaryTags(line: string): string {
  return line
    .replace(DETAILS_TAG_RE, escapeHtmlTag)
    .replace(SUMMARY_TAG_RE, escapeHtmlTag);
}

function deindentHtmlTableBlocks(lines: string[]): string[] {
  const next = [...lines];
  for (let i = 0; i < next.length; i += 1) {
    const openMatch = next[i].match(INDENTED_TABLE_OPEN_RE);
    if (!openMatch) continue;

    const start = i;
    let end = i;
    while (end < next.length && !TABLE_CLOSE_RE.test(next[end])) end += 1;
    if (end >= next.length) continue;

    const tableLines = next.slice(start, end + 1);
    const indents = tableLines
      .filter((line) => line.trim())
      .map((line) => line.match(/^ */)?.[0].length || 0);
    const commonIndent = Math.min(...indents);
    if (commonIndent < 4) continue;

    for (let j = start; j <= end; j += 1) {
      next[j] = next[j].startsWith(' '.repeat(commonIndent))
        ? next[j].slice(commonIndent)
        : next[j];
    }
    i = end;
  }
  return next;
}

export function sanitizeMarkdownBeforeRender(markdown: string): string {
  const lines = deindentHtmlTableBlocks(String(markdown || '').replace(/\r\n/g, '\n').split('\n'));
  let escapeFollowingSummary = false;

  return lines.map((line) => {
    const hasTranslationLabel = TRANSLATION_LABEL_RE.test(line);
    const hasDetailsTag = DETAILS_TAG_RE.test(line);
    DETAILS_TAG_RE.lastIndex = 0;

    if (hasTranslationLabel && hasDetailsTag) {
      escapeFollowingSummary = true;
      return escapeDetailsAndSummaryTags(line);
    }

    if (escapeFollowingSummary && /^\s*<summary\b/i.test(line)) {
      escapeFollowingSummary = false;
      return escapeDetailsAndSummaryTags(line);
    }

    if (line.trim()) {
      escapeFollowingSummary = false;
    }
    return line;
  }).join('\n');
}
