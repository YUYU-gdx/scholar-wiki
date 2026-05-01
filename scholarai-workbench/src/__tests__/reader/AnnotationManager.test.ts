import { describe, it, expect, beforeEach } from 'vitest';
import { annotationManager } from '../../components/reader/AnnotationManager';
import type { AnnotationCreate } from '../../components/reader/types';
import 'fake-indexeddb/auto';

describe('AnnotationManager', () => {
  it('adds and retrieves annotations by paper_id', async () => {
    const create: AnnotationCreate = {
      paper_id: 'paper-1',
      library_id: 'lib-1',
      type: 'highlight',
      page_index: 0,
      rects: [{ x: 10, y: 20, width: 100, height: 20, page_index: 0 }],
      text: 'test text',
      comment: '',
      color: '#ffeb3b',
      ink_paths: [],
      linked_node_ids: [],
    };
    const ann = await annotationManager.add(create);
    expect(ann.id).toBeDefined();
    expect(ann.type).toBe('highlight');

    const all = await annotationManager.getAllByPaper('paper-1');
    expect(all).toHaveLength(1);
    expect(all[0].text).toBe('test text');
  });

  it('updates annotation comment', async () => {
    const ann = await annotationManager.add({
      paper_id: 'paper-2', library_id: 'lib-1', type: 'note',
      page_index: 0, rects: [], text: '', comment: 'old', color: '#ffff00',
      ink_paths: [], linked_node_ids: [],
    });
    await annotationManager.update(ann.id, { comment: 'new comment' });
    const all = await annotationManager.getAllByPaper('paper-2');
    expect(all[0].comment).toBe('new comment');
  });

  it('removes annotation', async () => {
    const ann = await annotationManager.add({
      paper_id: 'paper-3', library_id: 'lib-1', type: 'underline',
      page_index: 1, rects: [], text: '', comment: '', color: '#00ff00',
      ink_paths: [], linked_node_ids: [],
    });
    await annotationManager.remove(ann.id);
    const all = await annotationManager.getAllByPaper('paper-3');
    expect(all).toHaveLength(0);
  });
});
