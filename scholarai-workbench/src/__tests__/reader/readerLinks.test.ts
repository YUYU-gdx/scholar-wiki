import { describe, expect, it } from 'vitest';
import { resolveMarkdownLinkPath } from '../../components/reader/readerLinks';

describe('reader markdown links', () => {
  it('resolves a relative markdown link against the current markdown file', () => {
    expect(resolveMarkdownLinkPath('../other/Next Paper.md#intro', 'C:\\papers\\current\\Current.md')).toBe('C:\\papers\\other\\Next Paper.md');
  });

  it('extracts a Windows path from a file URL markdown link', () => {
    expect(resolveMarkdownLinkPath('file:///C:/papers/Next%20Paper.md', 'C:\\papers\\Current.md')).toBe('C:\\papers\\Next Paper.md');
  });
});
