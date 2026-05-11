import { describe, expect, it } from 'vitest';
import { isSelectionInside } from '../../components/reader/selectionScope';

describe('isSelectionInside', () => {
  it('returns false when selection is outside container', () => {
    const container = document.createElement('div');
    const outside = document.createElement('div');
    const text = document.createTextNode('outside text');
    outside.appendChild(text);
    document.body.appendChild(container);
    document.body.appendChild(outside);

    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, 6);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);

    expect(isSelectionInside(container, sel)).toBe(false);
  });
});

