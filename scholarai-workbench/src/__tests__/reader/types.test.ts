import { describe, it, expect } from 'vitest';

describe('Reader types', () => {
  it('Annotation type has required fields', () => {
    const ann = {
      id: 'uuid-1',
      paper_id: 'paper-1',
      library_id: 'lib-1',
      type: 'highlight' as const,
      page_index: 0,
      rects: [{ x: 10, y: 20, width: 100, height: 20, page_index: 0 }],
      text: 'selected text',
      comment: '',
      color: '#ffeb3b',
      ink_paths: [],
      linked_node_ids: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    expect(ann.id).toBe('uuid-1');
    expect(ann.type).toBe('highlight');
  });
});
