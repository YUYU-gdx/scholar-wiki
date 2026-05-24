import { describe, expect, it } from 'vitest';
import {
  clearReaderFindMarks,
  findFirstRenderedTextBlock,
  highlightReaderFindMatches,
  setActiveReaderFindMatch,
} from '../../components/reader/ReaderFind';

describe('ReaderFind', () => {
  it('highlights rendered text matches and ignores hidden nodes', () => {
    const root = document.createElement('div');
    root.innerHTML = [
      '<div class="reader-markdown">',
      '<p>Supply chain resilience improves resilience.</p>',
      '<p hidden>resilience hidden metadata</p>',
      '</div>',
    ].join('');

    const content = root.querySelector('.reader-markdown') as HTMLElement;
    const matches = highlightReaderFindMatches(content, 'resilience');

    expect(matches).toHaveLength(2);
    expect(content.querySelectorAll('mark.reader-find-match')).toHaveLength(2);

    setActiveReaderFindMatch(matches, 1);
    expect(content.querySelectorAll('mark.reader-find-active')).toHaveLength(1);

    clearReaderFindMarks(content);
    expect(content.querySelectorAll('mark.reader-find-match')).toHaveLength(0);
    expect(content.textContent).toContain('Supply chain resilience improves resilience.');
  });

  it('finds the first visible rendered text block for external jumps', () => {
    const root = document.createElement('div');
    root.innerHTML = [
      '<h1>Title</h1>',
      '<p>First paragraph.</p>',
      '<blockquote>Target evidence sentence.</blockquote>',
    ].join('');

    const hit = findFirstRenderedTextBlock(root, ['target evidence']);
    expect(hit?.tagName).toBe('BLOCKQUOTE');
  });
});
