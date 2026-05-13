import type { PaperFiles } from '../../types';

export interface NoteBlock {
  id: string;
  quote: string;
  note: string;
  time: string;
}

const NOTES_PATH_CACHE_KEY = 'kn_reader_notes_md_path_v1';

function readNotesPathCache(): Record<string, string> {
  try {
    const raw = localStorage.getItem(NOTES_PATH_CACHE_KEY);
    if (!raw) return {};
    const obj = JSON.parse(raw);
    return obj && typeof obj === 'object' ? obj as Record<string, string> : {};
  } catch {
    return {};
  }
}

function writeNotesPathCache(next: Record<string, string>): void {
  try {
    localStorage.setItem(NOTES_PATH_CACHE_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
}

function notesPathKey(libraryId: string, paperId: string): string {
  return `${String(libraryId || '').trim()}::${String(paperId || '').trim()}`;
}

export function getRecordedNotesMarkdownPath(libraryId: string, paperId: string): string {
  return String(readNotesPathCache()[notesPathKey(libraryId, paperId)] || '');
}

export function setRecordedNotesMarkdownPath(libraryId: string, paperId: string, mdPath: string): void {
  const all = readNotesPathCache();
  all[notesPathKey(libraryId, paperId)] = String(mdPath || '');
  writeNotesPathCache(all);
}

export function listRecordedNotesMarkdownPaths(libraryId: string, paperId: string): string[] {
  const byKey = String(getRecordedNotesMarkdownPath(libraryId, paperId) || '').trim();
  return byKey ? [byKey] : [];
}

function normalizeNewlines(s: string): string {
  return String(s || '').replace(/\r\n/g, '\n');
}

function normalizeForMatch(s: string): string {
  return String(s || '').replace(/\s+/g, ' ').trim();
}

function dedupeReaderNotesHeadings(raw: string): string {
  return String(raw || '').replace(/(?:\n\s*## Reader Notes\s*){2,}/g, '\n\n## Reader Notes\n\n');
}

function normalizeWithMap(raw: string): { normalized: string; map: number[] } {
  const src = String(raw || '');
  const map: number[] = [];
  let normalized = '';
  let inWs = false;
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    const ws = /\s/.test(ch);
    if (ws) {
      if (inWs) continue;
      inWs = true;
      normalized += ' ';
      map.push(i);
      continue;
    }
    inWs = false;
    normalized += ch;
    map.push(i);
  }
  return { normalized: normalized.trim(), map };
}

function findQuoteInsertIndex(raw: string, quote: string): number {
  const src = normalizeNewlines(raw);
  const picked = String(quote || '').trim();
  if (!picked) return src.length;
  // eslint-disable-next-line no-console
  console.log('[notes] findQuoteInsertIndex input', {
    pickedLen: picked.length,
    pickedHead: picked.slice(0, 120),
    pickedTail: picked.slice(-80),
    srcLen: src.length,
  });
  const exact = src.indexOf(picked);
  if (exact >= 0) {
    const endOfSelection = exact + picked.length;
    const tail = src.slice(endOfSelection);
    const endInTail = tail.indexOf('\n');
    const contextBefore = src.slice(Math.max(0, exact - 60), exact);
    const contextAfter = src.slice(endOfSelection, endOfSelection + 80);
    const insertAt = endInTail >= 0 ? endOfSelection + endInTail : src.length;
    const insertContext = src.slice(Math.max(0, insertAt - 40), insertAt + 80);
    // eslint-disable-next-line no-console
    console.log('[notes] find index by exact', {
      exact,
      endOfSelection,
      endInTail,
      insertAt,
      srcLen: src.length,
      contextBefore,
      matchHead: src.slice(exact, exact + 80),
      contextAfter,
      insertContext,
    });
    return insertAt;
  }

  const rawNorm = normalizeWithMap(src);
  const pickedNorm = normalizeForMatch(picked);
  const normIdx = rawNorm.normalized.indexOf(pickedNorm);
  if (normIdx < 0) {
    // eslint-disable-next-line no-console
    console.warn('[notes] find index failed: no exact or normalized match', {
      pickedLen: picked.length,
      pickedNormLen: pickedNorm.length,
      pickedNormHead: pickedNorm.slice(0, 120),
      srcLen: src.length,
      srcNormHead: rawNorm.normalized.slice(0, 200),
    });
    return src.length;
  }
  const normEnd = normIdx + Math.max(0, pickedNorm.length - 1);
  const rawEnd = rawNorm.map[Math.max(0, Math.min(normEnd, rawNorm.map.length - 1))] ?? src.length;
  const endOfSelection = Math.min(src.length, rawEnd + 1);
  const tail = src.slice(endOfSelection);
  const endInTail = tail.indexOf('\n');
  const insertAt = endInTail >= 0 ? endOfSelection + endInTail : src.length;
  const insertContext = src.slice(Math.max(0, insertAt - 40), insertAt + 80);
  // eslint-disable-next-line no-console
  console.log('[notes] find index by normalized map', {
    normIdx,
    normEnd,
    rawEnd,
    endOfSelection,
    endInTail,
    insertAt,
    srcLen: src.length,
    normMatchHead: rawNorm.normalized.slice(normIdx, normIdx + 80),
    insertContext,
  });
  if (endInTail >= 0) return insertAt;
  return src.length;
}

export function buildNoteBlock(id: string, quote: string, note: string, time?: string): string {
  const now = time || new Date().toISOString();
  return `\n\n> [!NOTE] Reader Note\n> Note ID: ${id}\n> Quote:\n> ${String(quote || '').trim()}\n>\n> Note:\n> ${String(note || '').trim()}\n>\n> Time:\n> ${now}\n`;
}

export function extractNoteBlocks(raw: string): Array<{ id: string; start: number; end: number; text: string }> {
  const src = normalizeNewlines(raw);
  const out: Array<{ id: string; start: number; end: number; text: string }> = [];
  const marker = '> [!NOTE] Reader Note';
  let pos = 0;
  while (pos < src.length) {
    const start = src.indexOf(marker, pos);
    if (start < 0) break;
    let end = src.indexOf('\n\n', start + marker.length);
    if (end < 0) end = src.length;
    const seg = src.slice(start, end);
    const idMatch = seg.match(/>\s*Note ID:\s*([a-zA-Z0-9-]+)/);
    out.push({
      id: idMatch ? String(idMatch[1]) : '',
      start,
      end,
      text: seg,
    });
    pos = end + 2;
  }
  return out;
}

export async function ensureMarkdownPathForNotes(files: PaperFiles, paperId: string): Promise<string> {
  const existing = String(files.files.markdown?.path || '').trim();
  if (existing) return existing;
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return '';
  const base = String(files.files.pdf?.path || files.files.html?.path || '').trim();
  if (!base) return '';
  const dir = base.replace(/[\\/][^\\/]*$/, '');
  const mdPath = `${dir}${dir.endsWith('\\') ? '' : '\\'}reader_notes.md`;
  const probe = await shell.readLocalText(mdPath);
  if (!probe.ok) {
    const content = `# ${paperId}\n\n## Reader Notes\n`;
    await shell.writeLocalText(mdPath, content);
  }
  files.files.markdown = {
    path: mdPath,
    name: 'reader_notes.md',
    size_bytes: 0,
  };
  setRecordedNotesMarkdownPath(files.library_id, files.paper_id || paperId, mdPath);
  return mdPath;
}

export async function upsertNoteInMarkdown(markdownPath: string, noteId: string, quote: string, note: string): Promise<void> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) return;
  let read = await shell.readLocalText(markdownPath);
  if (!read.ok) {
    const init = '## Reader Notes\n';
    const created = await shell.writeLocalText(markdownPath, init);
    if (!created.ok) {
      // eslint-disable-next-line no-console
      console.warn('[notes] upsert failed: cannot create markdown file', { markdownPath, error: created.error });
      return;
    }
    read = await shell.readLocalText(markdownPath);
    if (!read.ok) {
      // eslint-disable-next-line no-console
      console.warn('[notes] upsert failed: cannot re-read markdown file', { markdownPath, error: read.error });
      return;
    }
  }
  const raw = normalizeNewlines(read.data || '');
  const marker = `> Note ID: ${noteId}`;
  const at = raw.indexOf(marker);
  const block = buildNoteBlock(noteId, quote, note);
  let next = raw;
  if (at >= 0) {
    const start = raw.lastIndexOf('> [!NOTE] Reader Note', at);
    if (start >= 0) {
      let end = raw.indexOf('\n\n', at + marker.length);
      if (end < 0) end = raw.length;
      next = `${raw.slice(0, start)}${block}${raw.slice(end)}`;
    }
  } else {
    const insertAt = findQuoteInsertIndex(raw, quote);
    // eslint-disable-next-line no-console
    console.log('[notes] upsert insertAt', {
      insertAt,
      rawLen: raw.length,
      fallback: insertAt >= raw.length,
      contextBefore: insertAt < raw.length ? raw.slice(Math.max(0, insertAt - 60), insertAt) : '(fallback)',
      contextAfter: insertAt < raw.length ? raw.slice(insertAt, insertAt + 80) : '(fallback)',
    });
    if (insertAt < raw.length) {
      next = `${raw.slice(0, insertAt)}${block}${raw.slice(insertAt)}`;
    } else {
      next = raw.includes('## Reader Notes') ? `${raw}${block}` : `${raw}\n\n## Reader Notes${block}`;
    }
  }
  next = dedupeReaderNotesHeadings(next.replace(/\n{3,}/g, '\n\n'));
  const wr = await shell.writeLocalText(markdownPath, next);
  if (!wr.ok) {
    // eslint-disable-next-line no-console
    console.warn('[notes] upsert write failed', { markdownPath, noteId, error: wr.error });
  }
}

export async function addNoteToMarkdownAtomic(markdownPath: string, noteId: string, quote: string, note: string): Promise<{ ok: boolean; raw: string }> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) {
    // eslint-disable-next-line no-console
    console.error('[notes] atomic: shell/runtime check failed', { hasShell: !!shell, runtime: shell?.runtime, markdownPath });
    return { ok: false, raw: '' };
  }
  let read = await shell.readLocalText(markdownPath);
  if (!read.ok) {
    const init = '## Reader Notes\n';
    const created = await shell.writeLocalText(markdownPath, init);
    if (!created.ok) return { ok: false, raw: '' };
    read = await shell.readLocalText(markdownPath);
    if (!read.ok) return { ok: false, raw: '' };
  }
  const src = normalizeNewlines(read.data || '');
  const marker = `> Note ID: ${noteId}`;
  const at = src.indexOf(marker);
  const block = buildNoteBlock(noteId, quote, note);
  let next = src;
  if (at >= 0) {
    const start = src.lastIndexOf('> [!NOTE] Reader Note', at);
    if (start >= 0) {
      let end = src.indexOf('\n\n', at + marker.length);
      if (end < 0) end = src.length;
      next = `${src.slice(0, start)}${block}${src.slice(end)}`;
    }
  } else {
    const insertAt = findQuoteInsertIndex(src, quote);
    // eslint-disable-next-line no-console
    console.log('[notes] add atomic insert position', { noteId, insertAt, srcLen: src.length, usedFallback: insertAt >= src.length });
    if (insertAt < src.length) next = `${src.slice(0, insertAt)}${block}${src.slice(insertAt)}`;
    else next = src.includes('## Reader Notes') ? `${src}${block}` : `${src}\n\n## Reader Notes${block}`;
  }
  next = dedupeReaderNotesHeadings(next.replace(/\n{3,}/g, '\n\n'));
  const wr = await shell.writeLocalText(markdownPath, next);
  if (!wr.ok) {
    // eslint-disable-next-line no-console
    console.error('[notes] writeLocalText failed (atomic)', { markdownPath, error: wr.error });
    return { ok: false, raw: src };
  }
  const verify = await shell.readLocalText(markdownPath);
  if (!verify.ok) {
    // eslint-disable-next-line no-console
    console.error('[notes] read-back verify failed (atomic)', { markdownPath, error: verify.error });
    return { ok: false, raw: src };
  }
  const verifyRaw = normalizeNewlines(String(verify.data || ''));
  const markerFound = verifyRaw.includes(marker);
  if (!markerFound) {
    // eslint-disable-next-line no-console
    console.error('[notes] marker NOT found after write (atomic)', { marker, verifyLen: verifyRaw.length });
  }
  return { ok: markerFound, raw: verifyRaw };
}

function findInsertIndexByLine(raw: string, lineEnd: number): number {
  const src = normalizeNewlines(raw);
  const lines = src.split('\n');
  const targetLine = Math.max(0, Math.min(lineEnd, Math.max(0, lines.length - 1)));
  let offset = 0;
  for (let i = 0; i < targetLine + 1; i += 1) {
    offset += lines[i].length;
    if (i < lines.length - 1) offset += 1;
  }
  const tail = src.slice(offset);
  const endInTail = tail.indexOf('\n');
  return endInTail >= 0 ? offset + endInTail : src.length;
}

export async function addNoteToMarkdownAtomicByLine(
  markdownPath: string,
  noteId: string,
  quote: string,
  note: string,
  lineEnd: number,
): Promise<{ ok: boolean; raw: string }> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) {
    // eslint-disable-next-line no-console
    console.error('[notes] atomicByLine: shell/runtime check failed', { hasShell: !!shell, runtime: shell?.runtime, markdownPath });
    return { ok: false, raw: '' };
  }
  let read = await shell.readLocalText(markdownPath);
  if (!read.ok) {
    // eslint-disable-next-line no-console
    console.warn('[notes] atomicByLine: read failed, trying init', { markdownPath, error: read.error });
    const init = '## Reader Notes\n';
    const created = await shell.writeLocalText(markdownPath, init);
    if (!created.ok) {
      // eslint-disable-next-line no-console
      console.error('[notes] atomicByLine: init create failed', { markdownPath, error: created.error });
      return { ok: false, raw: '' };
    }
    read = await shell.readLocalText(markdownPath);
    if (!read.ok) {
      // eslint-disable-next-line no-console
      console.error('[notes] atomicByLine: re-read after init failed', { markdownPath, error: read.error });
      return { ok: false, raw: '' };
    }
  }
  const src = normalizeNewlines(read.data || '');
  const marker = `> Note ID: ${noteId}`;
  const at = src.indexOf(marker);
  const block = buildNoteBlock(noteId, quote, note);
  let next = src;
  if (at >= 0) {
    const start = src.lastIndexOf('> [!NOTE] Reader Note', at);
    if (start >= 0) {
      let end = src.indexOf('\n\n', at + marker.length);
      if (end < 0) end = src.length;
      next = `${src.slice(0, start)}${block}${src.slice(end)}`;
    }
  } else {
    const insertAt = findInsertIndexByLine(src, lineEnd);
    // eslint-disable-next-line no-console
    console.log('[notes] atomicByLine insert', { noteId, lineEnd, insertAt, srcLen: src.length, hasReaderNotes: src.includes('## Reader Notes') });
    next = insertAt < src.length
      ? `${src.slice(0, insertAt)}${block}${src.slice(insertAt)}`
      : (src.includes('## Reader Notes') ? `${src}${block}` : `${src}\n\n## Reader Notes${block}`);
  }
  next = dedupeReaderNotesHeadings(next.replace(/\n{3,}/g, '\n\n'));
  const wr = await shell.writeLocalText(markdownPath, next);
  if (!wr.ok) {
    // eslint-disable-next-line no-console
    console.error('[notes] writeLocalText failed', { markdownPath, error: wr.error, ok: wr.ok });
    return { ok: false, raw: src };
  }
  const verify = await shell.readLocalText(markdownPath);
  if (!verify.ok) {
    // eslint-disable-next-line no-console
    console.error('[notes] read-back verify failed', { markdownPath, error: verify.error });
    return { ok: false, raw: src };
  }
  const verifyRaw = normalizeNewlines(String(verify.data || ''));
  const markerFound = verifyRaw.includes(marker);
  if (!markerFound) {
    // eslint-disable-next-line no-console
    console.error('[notes] marker NOT found after write', { marker, verifyLen: verifyRaw.length });
  }
  return { ok: markerFound, raw: verifyRaw };
}

export async function deleteNoteFromMarkdown(markdownPath: string, noteId: string, quote: string, note: string): Promise<boolean> {
  const shell = window.desktopShell;
  // eslint-disable-next-line no-console
  console.log('[notes] delete start', { markdownPath, noteId, hasQuote: !!String(quote || '').trim(), hasNote: !!String(note || '').trim() });
  if (!shell || shell.runtime !== 'electron' || !markdownPath) {
    // eslint-disable-next-line no-console
    console.warn('[notes] delete skipped: runtime/path invalid', { runtime: shell?.runtime, markdownPath });
    return false;
  }
  const read = await shell.readLocalText(markdownPath);
  if (!read.ok) {
    // eslint-disable-next-line no-console
    console.warn('[notes] delete read failed', { markdownPath, error: read.error });
    return false;
  }
  const originalRaw = normalizeNewlines(read.data || '');
  let raw = originalRaw;
  const marker = noteId ? `> Note ID: ${noteId}` : '';

  if (noteId) {
    const allBlocks = extractNoteBlocks(raw);
    const byId = allBlocks.find((b) => String(b.id) === String(noteId));
    if (byId) {
      raw = `${raw.slice(0, byId.start)}${raw.slice(byId.end)}`.replace(/\n{3,}/g, '\n\n');
      if (raw === originalRaw) {
        // eslint-disable-next-line no-console
        console.warn('[notes] delete no-op after id block branch', { noteId, markdownPath });
        return false;
      }
      await shell.writeLocalText(markdownPath, raw);
      const verify = await shell.readLocalText(markdownPath);
      const verifyRaw = normalizeNewlines(String(verify.data || ''));
      const changed = verify.ok && verifyRaw !== originalRaw;
      const removed = !verifyRaw.includes(marker);
      const ok = !!(verify.ok && changed && removed);
      // eslint-disable-next-line no-console
      console.log('[notes] delete verify by id block', { noteId, markdownPath, ok });
      return ok;
    }
  }

  const blocks = raw.split(/\n{2,}/);
  const q = String(quote || '').trim();
  const n = String(note || '').trim();
  const next = blocks.filter((b) => {
    if (!b.includes('[!NOTE] Reader Note')) return true;
    const bNorm = normalizeForMatch(b);
    const qNorm = normalizeForMatch(q);
    const nNorm = normalizeForMatch(n);
    if (qNorm && nNorm) return !(bNorm.includes(qNorm) && bNorm.includes(nNorm));
    if (qNorm) return !bNorm.includes(qNorm);
    if (nNorm) return !bNorm.includes(nNorm);
    return true;
  }).join('\n\n').replace(/\n{3,}/g, '\n\n');
  if (next === originalRaw) {
    // eslint-disable-next-line no-console
    console.warn('[notes] delete fallback no-op', { noteId, markdownPath });
    return false;
  }
  await shell.writeLocalText(markdownPath, next);
  const verify = await shell.readLocalText(markdownPath);
  const verifyRaw = normalizeNewlines(String(verify.data || ''));
  const removedById = marker ? !verifyRaw.includes(marker) : false;
  const changed = !!(verify.ok && verifyRaw !== originalRaw);
  const ok = !!(verify.ok && changed && (removedById || !marker));
  // eslint-disable-next-line no-console
  console.log('[notes] delete verify by fallback', { noteId, markdownPath, ok });
  return ok;
}

export async function deleteNoteFromMarkdownAny(
  markdownPaths: string[],
  noteId: string,
  quote: string,
  note: string,
): Promise<{ ok: boolean; path: string; attempted: string[] }> {
  const uniq = Array.from(new Set(markdownPaths.map((p) => String(p || '').trim()).filter(Boolean)));
  for (const p of uniq) {
    // eslint-disable-next-line no-await-in-loop
    const ok = await deleteNoteFromMarkdown(p, noteId, quote, note);
    if (ok) return { ok: true, path: p, attempted: uniq };
  }
  return { ok: false, path: uniq[0] || '', attempted: uniq };
}

export async function readMarkdownText(markdownPath: string): Promise<string> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) return '';
  const r = await shell.readLocalText(markdownPath);
  if (!r.ok) return '';
  return normalizeNewlines(String(r.data || ''));
}

export async function mergeNotesIntoMarkdown(sourcePath: string, targetPath: string): Promise<void> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !sourcePath || !targetPath || sourcePath === targetPath) return;
  const [srcR, tgtR] = await Promise.all([shell.readLocalText(sourcePath), shell.readLocalText(targetPath)]);
  if (!srcR.ok || !tgtR.ok) return;
  const src = normalizeNewlines(srcR.data || '');
  const tgt = normalizeNewlines(tgtR.data || '');
  const srcBlocks = extractNoteBlocks(src);
  const tgtBlocks = extractNoteBlocks(tgt);
  const tgtIds = new Set(tgtBlocks.map((b) => b.id).filter(Boolean));
  let next = tgt;
  for (const b of srcBlocks) {
    if (b.id && tgtIds.has(b.id)) continue;
    next = next.includes('## Reader Notes') ? `${next}\n\n${b.text}\n` : `${next}\n\n## Reader Notes\n\n${b.text}\n`;
  }
  if (next !== tgt) {
    await shell.writeLocalText(targetPath, next.replace(/\n{3,}/g, '\n\n'));
  }
}

// ── Occurrence-based insertion (PDF↔markdown position mapping) ──────────

function normStr(s: string): string {
  return String(s || '').replace(/\s+/g, ' ').trim();
}

/**
 * Find the insert position for the Nth occurrence of anchorText in raw markdown,
 * ignoring existing [!NOTE] Reader Note blocks. Returns the position right after
 * the paragraph containing the match, or raw.length if not found.
 */
function findNthAnchorInsertPos(raw: string, anchorText: string, n: number): number {
  const src = normalizeNewlines(raw);
  const na = normStr(anchorText);
  if (!na || n <= 0) return src.length;

  // 1. Identify note block spans to exclude
  const noteBlocks = extractNoteBlocks(src);

  // 2. Build clean text: replace note blocks with spaces (preserve length)
  let clean = src;
  for (const nb of noteBlocks) {
    clean = clean.slice(0, nb.start) + ' '.repeat(nb.end - nb.start) + clean.slice(nb.end);
  }

  // 3. Build normalized clean → clean position map
  const normToClean: number[] = [];
  let normStrBuf = '';
  let inWs = false;
  for (let i = 0; i < clean.length; i++) {
    const ch = clean[i];
    const ws = /\s/.test(ch);
    if (ws) {
      if (!inWs) {
        normStrBuf += ' ';
        normToClean.push(i);
        inWs = true;
      }
    } else {
      normStrBuf += ch;
      normToClean.push(i);
      inWs = false;
    }
  }
  const normText = normStrBuf.trim();

  // 4. Find Nth occurrence
  let searchFrom = 0;
  let count = 0;
  while (count < n) {
    const idx = normText.indexOf(na, searchFrom);
    if (idx < 0) return src.length; // not enough occurrences — fallback to end
    count++;
    if (count === n) {
      // Map back to clean position, then find paragraph end
      const normEnd = idx + na.length;
      const cleanPos =
        normEnd < normToClean.length
          ? normToClean[normEnd]
          : clean.length - 1;
      // Find next \n\n (paragraph boundary) at or after this position
      const paraEnd = clean.indexOf('\n\n', Math.min(cleanPos, clean.length));
      return paraEnd >= 0 ? paraEnd + 2 : src.length;
    }
    searchFrom = idx + 1;
  }

  return src.length;
}

export async function addNoteToMarkdownByOccurrence(
  markdownPath: string,
  noteId: string,
  quote: string,
  note: string,
  anchorText: string,
  occurrence: number,
): Promise<{ ok: boolean; raw: string }> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) {
    // eslint-disable-next-line no-console
    console.error('[notes] occ: shell/runtime check failed', { hasShell: !!shell, runtime: shell?.runtime, markdownPath });
    return { ok: false, raw: '' };
  }

  let read = await shell.readLocalText(markdownPath);
  if (!read.ok) {
    const init = '## Reader Notes\n';
    const created = await shell.writeLocalText(markdownPath, init);
    if (!created.ok) return { ok: false, raw: '' };
    read = await shell.readLocalText(markdownPath);
    if (!read.ok) return { ok: false, raw: '' };
  }

  const src = normalizeNewlines(read.data || '');
  const marker = `> Note ID: ${noteId}`;

  // Already exists? Update in-place
  const at = src.indexOf(marker);
  const block = buildNoteBlock(noteId, quote, note);
  if (at >= 0) {
    const start = src.lastIndexOf('> [!NOTE] Reader Note', at);
    if (start >= 0) {
      let end = src.indexOf('\n\n', at + marker.length);
      if (end < 0) end = src.length;
      const next = `${src.slice(0, start)}${block}${src.slice(end)}`;
      const wr = await shell.writeLocalText(markdownPath, next);
      if (!wr.ok) return { ok: false, raw: src };
      return { ok: true, raw: next };
    }
  }

  // New note: insert after the Nth occurrence of anchor text
  const insertAt = findNthAnchorInsertPos(src, anchorText, occurrence);
  // eslint-disable-next-line no-console
  console.log('[notes] occ insert', { noteId, occurrence, anchorLen: anchorText.length, insertAt, srcLen: src.length, fallback: insertAt >= src.length });

  const next =
    insertAt < src.length
      ? `${src.slice(0, insertAt)}${block}${src.slice(insertAt)}`
      : src.includes('## Reader Notes')
        ? `${src}${block}`
        : `${src}\n\n## Reader Notes${block}`;

  const deduped = dedupeReaderNotesHeadings(next.replace(/\n{3,}/g, '\n\n'));
  const wr = await shell.writeLocalText(markdownPath, deduped);
  if (!wr.ok) {
    // eslint-disable-next-line no-console
    console.error('[notes] occ write failed', { markdownPath, error: wr.error });
    return { ok: false, raw: src };
  }

  const verify = await shell.readLocalText(markdownPath);
  if (!verify.ok) return { ok: false, raw: src };
  const verifyRaw = normalizeNewlines(String(verify.data || ''));
  return { ok: verifyRaw.includes(marker), raw: verifyRaw };
}
