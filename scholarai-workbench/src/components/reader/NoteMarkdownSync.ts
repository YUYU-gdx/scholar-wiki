export interface NoteBlock {
  id: string;
  pageIndex: number;
  rect: string;
  quote: string;
  note: string;
  time: string;
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

export function buildNoteBlock(
  id: string,
  quote: string,
  note: string,
  opts?: { time?: string; pageIndex?: number; rect?: string },
): string {
  const time = opts?.time || new Date().toISOString();
  const pageLine = opts?.pageIndex != null && opts.pageIndex >= 0 ? `> Page: ${opts.pageIndex}\n` : '';
  const rectLine = opts?.rect ? `> Rect: ${opts.rect}\n` : '';
  return `\n\n> [!NOTE] Reader Note\n> Note ID: ${id}\n${pageLine}${rectLine}> Quote:\n> ${String(quote || '').trim()}\n>\n> Note:\n> ${String(note || '').trim()}\n>\n> Time:\n> ${time}\n`;
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
export async function upsertNoteInMarkdown(
  markdownPath: string,
  noteId: string,
  quote: string,
  note: string,
  opts?: { pageIndex?: number; rect?: string },
): Promise<void> {
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
  const block = buildNoteBlock(noteId, quote, note, { pageIndex: opts?.pageIndex, rect: opts?.rect });
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