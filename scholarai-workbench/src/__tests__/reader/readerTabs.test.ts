import { describe, expect, it } from 'vitest';
import { createFileReaderTab } from '../../components/reader/readerTabs';

describe('reader tab helpers', () => {
  it('creates a markdown file tab from a local path', () => {
    const tab = createFileReaderTab('C:\\papers\\A Study.md', 'ai_washing');

    expect(tab).toMatchObject({
      paperId: 'file:C:\\papers\\A Study.md',
      libraryId: 'ai_washing',
      type: 'markdown',
      path: 'C:\\papers\\A Study.md',
      title: 'A Study.md',
    });
  });
});
