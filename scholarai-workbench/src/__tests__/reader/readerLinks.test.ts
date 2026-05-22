import { describe, expect, it } from 'vitest';
import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import {
  LOCAL_MARKDOWN_ALLOWED_URI_REGEXP,
  normalizePaperLinkKey,
  resolveMarkdownLinkPath,
  validateReaderMarkdownLink,
} from '../../components/reader/readerLinks';

describe('reader markdown links', () => {
  it('resolves a relative markdown link against the current markdown file', () => {
    expect(resolveMarkdownLinkPath('../other/Next Paper.md#intro', 'C:\\papers\\current\\Current.md')).toBe('C:\\papers\\other\\Next Paper.md');
  });

  it('extracts a Windows path from a file URL markdown link', () => {
    expect(resolveMarkdownLinkPath('file:///C:/papers/Next%20Paper.md', 'C:\\papers\\Current.md')).toBe('C:\\papers\\Next Paper.md');
  });

  it('extracts a Windows path from a file URL html link for direct file navigation', () => {
    expect(resolveMarkdownLinkPath('file:///C:/papers/Next%20Paper.html', 'C:\\papers\\Current.md')).toBe('C:\\papers\\Next Paper.html');
  });

  it('normalizes extracted related-paper html links to the same key as graph paper paths', () => {
    expect(normalizePaperLinkKey('file:///C:/papers/Unveiling%20AI%20washing_%20Bridging.html')).toBe('unveiling ai washing bridging');
    expect(normalizePaperLinkKey('C:/papers/Unveiling AI washing_ Bridging.html')).toBe('unveiling ai washing bridging');
  });

  it('preserves local related-paper links during markdown rendering', () => {
    const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
    md.validateLink = validateReaderMarkdownLink;

    const html = DOMPurify.sanitize(
      md.render('[Unveiling AI washing](file:///C:/papers/Unveiling%20AI%20washing.html)'),
      { ALLOWED_URI_REGEXP: LOCAL_MARKDOWN_ALLOWED_URI_REGEXP },
    );

    expect(html).toContain('href="file:///C:/papers/Unveiling%20AI%20washing.html"');
    expect(html).toContain('Unveiling AI washing');
  });
});
