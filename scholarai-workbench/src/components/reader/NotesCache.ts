/**
 * In-memory notes cache 鈥?single source of truth is the .md file.
 * No IndexedDB. Notes are parsed from markdown [!NOTE] Reader Note blocks.
 */
export interface NoteEntry {
  id: string;
  paperId: string;
  libraryId: string;
  docType: 'pdf' | 'markdown';
  pageIndex: number;
  rect: string;
  quads: string;
  selectedText: string;
  noteText: string;
  markdownPath: string;
  createdAt: string;
  updatedAt: string;
}

const cache = new Map<string, NoteEntry[]>();

function parseNoteBlocks(raw: string): Array<{ id: string; pageIndex: number; rect: string; quads: string; quote: string; note: string; time: string }> {
  const src = String(raw || '').replace(/\r\n/g, '\n');
  const out: Array<{ id: string; pageIndex: number; rect: string; quads: string; quote: string; note: string; time: string }> = [];
  const marker = '> [!NOTE] Reader Note';
  let pos = 0;
  while (pos < src.length) {
    const start = src.indexOf(marker, pos);
    if (start < 0) break;
    let end = src.indexOf(marker, start + marker.length);
    if (end < 0) end = src.length;
    const seg = src.slice(start, end);
    const idMatch = seg.match(/>\s*Note ID:\s*([a-zA-Z0-9-]+)/);
    const pageMatch = seg.match(/>\s*Page:\s*(\d+)/);
    const rectMatch = seg.match(/>\s*Rect:\s*([\d.,\s]+)/);
    const quadsMatch = seg.match(/>\s*Quads:\s*([^\n\r]+)/);
    const quoteMatch = seg.match(/>\\s*Quote:\\s*\\n(?:>\\s*\\n)*>\\s*([\\s\\S]*?)\\n>\\s*\\n>\\s*Note:/i);
    const noteMatch = seg.match(/>\\s*Note:\\s*\\n(?:>\\s*\\n)*>\\s*([\\s\\S]*?)\\n>\\s*\\n>\\s*Time:/i);
    const timeMatch = seg.match(/>\\s*Time:\\s*(.+)/i);
    out.push({
      id: idMatch ? String(idMatch[1]) : '',
      pageIndex: pageMatch ? parseInt(String(pageMatch[1]), 10) : 0,
      rect: rectMatch ? String(rectMatch[1]).trim() : '',
      quads: quadsMatch ? String(quadsMatch[1]).trim() : '',
      quote: quoteMatch
        ? String(quoteMatch[1] || '').split('\n').map((ln) => ln.replace(/^>\s?/, '')).join('\n').trim()
        : '',
      note: noteMatch
        ? String(noteMatch[1] || '').split('\n').map((ln) => ln.replace(/^>\s?/, '')).join('\n').trim()
        : '',
      time: String(timeMatch?.[1] || '').trim(),
    });
    pos = end;
  }
  return out;
}

export const notesCache = {
  /** Build cache from raw markdown content */
  load(raw: string, paperId: string, libraryId: string, markdownPath: string): NoteEntry[] {
    const blocks = parseNoteBlocks(raw);
    const entries: NoteEntry[] = blocks.map((b) => ({
      id: b.id,
      paperId,
      libraryId,
      docType: 'markdown' as const,
      pageIndex: b.pageIndex,
      rect: b.rect,
      quads: b.quads,
      selectedText: b.quote,
      noteText: b.note,
      markdownPath,
      createdAt: b.time || new Date(0).toISOString(),
      updatedAt: b.time || new Date(0).toISOString(),
    }));
    cache.set(paperId, entries);
    return entries;
  },

  /** Get cached notes for a paper */
  get(paperId: string): NoteEntry[] {
    return cache.get(paperId) || [];
  },

  /** Clear cache for a paper (force re-read on next load) */
  invalidate(paperId: string) {
    cache.delete(paperId);
  },
};
