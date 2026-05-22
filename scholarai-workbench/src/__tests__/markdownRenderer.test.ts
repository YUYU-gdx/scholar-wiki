import { describe, expect, it } from 'vitest';
import { renderMarkdownToHtml } from '../components/markdown/markdownRenderer';

describe('shared markdown renderer', () => {
  it('uses the same standard markdown features for chat and document profiles', async () => {
    const source = [
      '- [x] done',
      '',
      'Term',
      ': Definition',
      '',
      'Marked ==text== and footnote[^1].',
      '',
      '[^1]: footnote body',
    ].join('\n');

    const chat = await renderMarkdownToHtml(source, { profile: 'chat' });
    const document = await renderMarkdownToHtml(source, { profile: 'document' });

    for (const html of [chat, document]) {
      expect(html).toContain('type="checkbox"');
      expect(html).toContain('checked');
      expect(html).toContain('<dl>');
      expect(html).toContain('<mark>text</mark>');
      expect(html).toContain('footnote');
    }
  });

  it('keeps reader-only source line attributes out of chat output', async () => {
    const source = '## Heading\n\nBody';

    const chat = await renderMarkdownToHtml(source, { profile: 'chat' });
    const document = await renderMarkdownToHtml(source, { profile: 'document' });

    expect(chat).not.toContain('data-src-line-start');
    expect(document).toContain('data-src-line-start');
  });

  it('sanitizes scripts in every profile', async () => {
    const source = '<script>alert(1)</script>\n\n[ok](javascript:alert(1))';

    const chat = await renderMarkdownToHtml(source, { profile: 'chat' });
    const document = await renderMarkdownToHtml(source, { profile: 'document' });

    expect(chat).not.toContain('<script');
    expect(chat).not.toContain('href="javascript:');
    expect(document).not.toContain('<script');
    expect(document).not.toContain('href="javascript:');
  });
});
