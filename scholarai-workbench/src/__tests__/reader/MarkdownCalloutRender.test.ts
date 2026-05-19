import { describe, expect, it } from 'vitest';
import MarkdownIt from 'markdown-it';
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

  it('keeps inline translation body as rendered body text instead of folding it into the title', () => {
    const doc = new DOMParser().parseFromString(
      '<blockquote><p>[!TRANSLATION] &#x8bd1;&#x6587; &#x968f;&#x7740;&#x4f01;&#x4e1a;&#x65e5;&#x76ca;&#x5938;&#x5927;AI&#x5e94;&#x7528;&#x3002;</p></blockquote>',
      'text/html',
    );

    transformCallouts(doc);

    const callout = doc.querySelector('.callout-translation');
    expect(callout?.querySelector('.callout-title')?.textContent).toBe('\u8bd1\u6587');
    expect(callout?.querySelector('p')?.textContent).toBe('\u968f\u7740\u4f01\u4e1a\u65e5\u76ca\u5938\u5927AI\u5e94\u7528\u3002');
  });

  it('formats translation and reader-note blocks with the same blockquote callout structure', () => {
    expect(buildMarkdownCallout('TRANSLATION', '译文', ['翻译内容'])).toBe(
      '> [!TRANSLATION] 译文\n> 翻译内容',
    );

    expect(buildMarkdownCallout('NOTE', 'Reader Note', ['', 'Note ID: n1', '', 'Quote:', '原文', '', 'Note:', '笔记'])).toBe(
      '> [!NOTE] Reader Note\n>\n> Note ID: n1\n>\n> Quote:\n> 原文\n>\n> Note:\n> 笔记',
    );
  });

  it('keeps translation body on the next blockquote line for plain text affiliation lines', () => {
    const md = new MarkdownIt({ html: true, breaks: false });
    const raw = '> [!TRANSLATION] 译文\n> b 商学院，西华师范大学，南充市，四川省，中国';
    const html = md.render(raw);
    const doc = new DOMParser().parseFromString(html, 'text/html');

    transformCallouts(doc);

    const callout = doc.querySelector('.callout-translation');
    expect(callout?.querySelector('.callout-title')?.textContent).toBe('译文');
    expect(callout?.querySelector('p')?.textContent).toContain('b 商学院');
  });
});
