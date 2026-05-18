const TRANSLATION_LABEL_RE = /class=["']translation-label["']/i;
const DETAILS_TAG_RE = /<\/?details\b[^>]*>/gi;
const SUMMARY_TAG_RE = /<\/?summary\b[^>]*>/gi;

function escapeHtmlTag(tag: string): string {
  return tag.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeDetailsAndSummaryTags(line: string): string {
  return line
    .replace(DETAILS_TAG_RE, escapeHtmlTag)
    .replace(SUMMARY_TAG_RE, escapeHtmlTag);
}

export function sanitizeMarkdownBeforeRender(markdown: string): string {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
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
