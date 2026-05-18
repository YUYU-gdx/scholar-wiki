import { describe, expect, it } from 'vitest';
import { transformCallouts } from '../../components/reader/MarkdownEditor';

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
});
