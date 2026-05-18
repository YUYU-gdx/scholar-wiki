import { describe, expect, it } from 'vitest';
import { buildNoteBlock } from '../../components/reader/NoteMarkdownSync';

describe('buildNoteBlock', () => {
  it('writes reader notes as the shared markdown callout block format', () => {
    expect(buildNoteBlock('n1', '原文', '笔记', { time: '2026-05-18T00:00:00.000Z' })).toBe(
      [
        '',
        '',
        '> [!NOTE] Reader Note',
        '>',
        '> Note ID: n1',
        '>',
        '> Quote:',
        '> 原文',
        '>',
        '> Note:',
        '> 笔记',
        '>',
        '> Time:',
        '> 2026-05-18T00:00:00.000Z',
        '',
      ].join('\n'),
    );
  });
});
