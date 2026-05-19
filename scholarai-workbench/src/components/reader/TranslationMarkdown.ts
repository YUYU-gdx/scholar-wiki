const TRANSLATION_CALLOUT_START_RE = /^\s*>\s*\[!TRANSLATION\](?:\s|$)/i;
const LEGACY_TRANSLATION_START_RE = /^\s*(?:translation\s*[:：]|\u8bd1\u6587\s*[:：]|\u3010\u8bd1\u6587\u3011|<span\s+class=["']translation-label["']>\u3010\u8bd1\u6587\u3011<\/span>\s*[:：])/i;
const BLOCKQUOTE_LINE_RE = /^\s*>/;

export function hasTranslationBlocks(markdown: string): boolean {
  return String(markdown || '')
    .split(/\r?\n/)
    .some((line) => TRANSLATION_CALLOUT_START_RE.test(line) || LEGACY_TRANSLATION_START_RE.test(line));
}

export function removeTranslationBlocks(markdown: string): string {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    if (TRANSLATION_CALLOUT_START_RE.test(lines[i] || '')) {
      i += 1;
      while (i < lines.length && BLOCKQUOTE_LINE_RE.test(lines[i] || '')) {
        i += 1;
      }
      while (i < lines.length && String(lines[i] || '').trim() === '') {
        i += 1;
      }
      continue;
    }
    if (LEGACY_TRANSLATION_START_RE.test(lines[i] || '')) {
      i += 1;
      while (i < lines.length && String(lines[i] || '').trim() !== '') {
        i += 1;
      }
      while (i < lines.length && String(lines[i] || '').trim() === '') {
        i += 1;
      }
      continue;
    }
    out.push(lines[i] || '');
    i += 1;
  }

  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}
