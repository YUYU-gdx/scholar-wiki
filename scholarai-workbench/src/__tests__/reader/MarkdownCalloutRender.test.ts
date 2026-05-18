import { describe, expect, it } from 'vitest';
import { buildMarkdownCallout, transformCallouts } from '../../components/reader/MarkdownCallout';

describe('transformCallouts', () => {
  it('renders translation callouts with a dedicated class and title', () => {
    const doc = new DOMParser().parseFromString(
      '<blockquote><p>[!TRANSLATION] 译文</p><p>翻译内容</p></blockquote>',
      'text/html',
    );

    transformCallouts(doc);

    const callout = doc.querySelector('.callout-translation');
    expect(callout).toBeTruthy();
    expect(callout?.querySelector('.callout-title')?.textContent).toBe('译文');
    expect(callout?.textContent).toContain('翻译内容');
  });

  it('formats translation and reader-note blocks with the same blockquote callout structure', () => {
    expect(buildMarkdownCallout('TRANSLATION', '译文', ['翻译内容'])).toBe(
      '> [!TRANSLATION] 译文\n> 翻译内容',
    );

    expect(buildMarkdownCallout('NOTE', 'Reader Note', ['', 'Note ID: n1', '', 'Quote:', '原文', '', 'Note:', '笔记'])).toBe(
      '> [!NOTE] Reader Note\n>\n> Note ID: n1\n>\n> Quote:\n> 原文\n>\n> Note:\n> 笔记',
    );
  });
});
