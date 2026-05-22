import { describe, expect, it } from 'vitest';
import {
  extractReaderChatSessionRef,
  upsertReaderChatSessionRef,
} from '../../components/reader/ReaderChatSessionMarkdown';

describe('ReaderChatSessionMarkdown', () => {
  it('stores the reader chat session in a hidden markdown comment', () => {
    const next = upsertReaderChatSessionRef('# Paper\n\nBody\n', {
      libraryId: 'lib-1',
      paperId: 'paper-1',
      sessionId: 'session-1',
    });

    expect(next).toContain('<!-- scholar-wiki-reader-chat-session ');
    expect(next).toContain('"sessionId":"session-1"');
    expect(extractReaderChatSessionRef(next, 'lib-1', 'paper-1')).toEqual({
      libraryId: 'lib-1',
      paperId: 'paper-1',
      sessionId: 'session-1',
    });
  });

  it('updates only the matching paper session comment', () => {
    const first = upsertReaderChatSessionRef('', {
      libraryId: 'lib-1',
      paperId: 'paper-1',
      sessionId: 'old-session',
    });
    const withOtherPaper = upsertReaderChatSessionRef(first, {
      libraryId: 'lib-1',
      paperId: 'paper-2',
      sessionId: 'other-session',
    });
    const updated = upsertReaderChatSessionRef(withOtherPaper, {
      libraryId: 'lib-1',
      paperId: 'paper-1',
      sessionId: 'new-session',
    });

    expect(extractReaderChatSessionRef(updated, 'lib-1', 'paper-1')?.sessionId).toBe('new-session');
    expect(extractReaderChatSessionRef(updated, 'lib-1', 'paper-2')?.sessionId).toBe('other-session');
    expect(updated).not.toContain('old-session');
  });
});
