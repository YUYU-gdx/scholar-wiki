import { describe, it, expect } from 'vitest';
import type { Annotation, AnnotationCreate, AnnotationType, InkPath, ViewerMode } from '../../components/reader/types';

describe('Reader types', () => {
  it('Annotation has all required fields', () => {
    const ann: Annotation = {
      id: 'uuid-1',
      paper_id: 'paper-1',
      library_id: 'lib-1',
      type: 'highlight',
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
    expect(ann.rects).toHaveLength(1);
    expect(ann.rects[0].page_index).toBe(0);
  });

  it('AnnotationCreate omits id, created_at, updated_at', () => {
    const create: AnnotationCreate = {
      paper_id: 'p1',
      library_id: 'l1',
      type: 'note',
      page_index: 2,
      rects: [],
      text: 'note text',
      comment: 'my note',
      color: '#ff0',
      ink_paths: [],
      linked_node_ids: [],
    };
    expect(create.type).toBe('note');
    expect(create.comment).toBe('my note');
  });

  it('InkPath has points array', () => {
    const path: InkPath = {
      points: [{ x: 10, y: 20 }, { x: 30, y: 40 }],
      width: 2,
      color: '#000',
    };
    expect(path.points).toHaveLength(2);
    expect(path.points[0].x).toBe(10);
  });

  it('ViewerMode union accepts all three values', () => {
    const modes: ViewerMode[] = ['edit', 'live-preview', 'read'];
    expect(modes).toHaveLength(3);
  });
});
