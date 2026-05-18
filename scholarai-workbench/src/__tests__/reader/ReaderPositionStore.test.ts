import { describe, expect, it, beforeEach } from 'vitest';
import { buildReaderPositionKey, readReaderPosition, writeReaderPosition } from '../../components/reader/ReaderPositionStore';

describe('ReaderPositionStore', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('persists scroll position per document key', () => {
    const key = buildReaderPositionKey({
      libraryId: 'lib-a',
      paperId: 'paper-1',
      absolutePath: 'C:\\papers\\paper-1.md',
      viewerType: 'markdown',
    });

    writeReaderPosition(key, { scrollTop: 420, scrollLeft: 7 });

    expect(readReaderPosition(key)).toMatchObject({
      scrollTop: 420,
      scrollLeft: 7,
    });
  });

  it('uses different keys for different viewer types of the same paper', () => {
    const markdownKey = buildReaderPositionKey({
      libraryId: 'lib-a',
      paperId: 'paper-1',
      absolutePath: 'C:\\papers\\paper-1.md',
      viewerType: 'markdown',
    });
    const pdfKey = buildReaderPositionKey({
      libraryId: 'lib-a',
      paperId: 'paper-1',
      absolutePath: 'C:\\papers\\paper-1.pdf',
      viewerType: 'pdf',
    });

    expect(markdownKey).not.toBe(pdfKey);
  });
});
