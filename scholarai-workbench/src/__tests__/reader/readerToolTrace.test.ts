import { describe, it, expect } from 'vitest';
import { toTimelineRow } from '../../components/reader/readerToolTrace';

describe('readerToolTrace', () => {
  it('normalizes tool_call event into timeline row', () => {
    const row = toTimelineRow({
      event: 'tool_call',
      name: 'rag_search',
      arguments: { query: 'abc', top_k: 3 },
      result: { hits: [{ title: 'P1', paper_id: 'paper-1' }] },
      status: 'running',
    });

    expect(row).not.toBeNull();
    expect(row?.kind).toBe('event');
    expect(row?.state).toBe('running');
    expect(row?.title).toContain('RAG');
    expect(row?.detail).toContain('abc');
  });
});
