/**
 * In-memory notes cache - single source of truth is the .md file.
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

function findReaderNoteBlockEnd(src: string, start: number): number {
  const marker = '> [!NOTE] Reader Note';
  const next = src.indexOf(marker, start + marker.length);
  return next >= 0 ? next : src.length;
}

function parseReaderNoteFields(seg: string): {
  id: string; pageIndex: number; rect: string; quads: string; quote: string; note: string; time: string;
} {
  const lines = String(seg || '').replace(/\r\n/g, '\n').split('\n')
    .map((ln) => ln.replace(/^\s*>\s?/, '').trimEnd());
  let id = '';
  let pageIndex = -1;
  let rect = '';
  let quads = '';
  let quote = '';
  let note = '';
  let time = '';
  let mode: '' | 'quote' | 'note' | 'time' = '';
  const quoteLines: string[] = [];
  const noteLines: string[] = [];
  const flush = () => {
    if (mode === 'quote') quote = quoteLines.join('\n').trim();
    if (mode === 'note') note = noteLines.join('\n').trim();
    mode = '';
  };
  for (const rawLine of lines) {
    const line = String(rawLine || '').trim();
    if (!line) continue;
    const idMatch = line.match(/^Note ID:\s*([a-zA-Z0-9-]+)/i);
    if (idMatch) { flush(); id = String(idMatch[1] || '').trim(); continue; }
    const pageMatch = line.match(/^Page:\s*(\d+)/i);
    if (pageMatch) { flush(); pageIndex = parseInt(String(pageMatch[1] || '0'), 10) || 0; continue; }
    const rectMatch = line.match(/^Rect:\s*(.+)$/i);
    if (rectMatch) { flush(); rect = String(rectMatch[1] || '').trim(); continue; }
    const quadsMatch = line.match(/^Quads:\s*(.+)$/i);
    if (quadsMatch) { flush(); quads = String(quadsMatch[1] || '').trim(); continue; }
    if (/^Quote:\s*$/i.test(line)) { flush(); mode = 'quote'; continue; }
    if (/^Note:\s*$/i.test(line)) { flush(); mode = 'note'; continue; }
    const timeMatch = line.match(/^Time:\s*(.*)$/i);
    if (timeMatch) {
      flush();
      const t = String(timeMatch[1] || '').trim();
      if (t) {
        time = t;
        break;
      }
      mode = 'time';
      continue;
    }
    if (mode === 'time') {
      const t = line.trim();
      if (t) time = t;
      break;
    }
    if (mode === 'quote') quoteLines.push(line);
    else if (mode === 'note') noteLines.push(line);
  }
  flush();
  return { id, pageIndex, rect, quads, quote, note, time };
}

function parseNoteBlocks(raw: string): Array<{ id: string; pageIndex: number; rect: string; quads: string; quote: string; note: string; time: string }> {
  const src = String(raw || '').replace(/\r\n/g, '\n');
  const out: Array<{ id: string; pageIndex: number; rect: string; quads: string; quote: string; note: string; time: string }> = [];
  const marker = '> [!NOTE] Reader Note';
  let pos = 0;
  while (pos < src.length) {
    const start = src.indexOf(marker, pos);
    if (start < 0) break;
    const end = findReaderNoteBlockEnd(src, start);
    const seg = src.slice(start, end);
    const parsed = parseReaderNoteFields(seg);
    out.push({
      id: parsed.id,
      pageIndex: parsed.pageIndex,
      rect: parsed.rect,
      quads: parsed.quads,
      quote: parsed.quote,
      note: parsed.note,
      time: parsed.time,
    });
    pos = Math.max(end, start + marker.length);
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
