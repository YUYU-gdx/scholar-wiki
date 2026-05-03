import type { PaperFiles } from '../../types';
import { getRecordedNotesMarkdownPath, mergeNotesIntoMarkdown, setRecordedNotesMarkdownPath } from './NoteMarkdownSync';
const API_BASE = '';

const FILES_CACHE_KEY = 'kn_reader_paper_files_cache_v1';
const FILES_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const memoryFilesCache = new Map<string, { ts: number; data: PaperFiles }>();

function cacheKey(paperId: string, libraryId: string, rawPaperId?: string): string {
  return `${String(libraryId || '').trim()}::${String(paperId || '').trim()}::${String(rawPaperId || '').trim()}`;
}

function readPersistentCache(): Record<string, { ts: number; data: PaperFiles }> {
  try {
    const raw = localStorage.getItem(FILES_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    return parsed as Record<string, { ts: number; data: PaperFiles }>;
  } catch {
    return {};
  }
}

function writePersistentCache(next: Record<string, { ts: number; data: PaperFiles }>): void {
  try {
    localStorage.setItem(FILES_CACHE_KEY, JSON.stringify(next));
  } catch {
    // ignore quota / serialization failures
  }
}

function getCachedFiles(key: string): PaperFiles | null {
  const mem = memoryFilesCache.get(key);
  if (mem && Date.now() - mem.ts <= FILES_CACHE_TTL_MS) return mem.data;
  const persistent = readPersistentCache()[key];
  if (persistent && Date.now() - Number(persistent.ts || 0) <= FILES_CACHE_TTL_MS) {
    memoryFilesCache.set(key, persistent);
    return persistent.data;
  }
  return null;
}

function setCachedFiles(key: string, data: PaperFiles): void {
  const entry = { ts: Date.now(), data };
  memoryFilesCache.set(key, entry);
  const persistent = readPersistentCache();
  persistent[key] = entry;
  writePersistentCache(persistent);
}

async function validateCachedFiles(files: PaperFiles): Promise<boolean> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return true;
  const candidates = [files.files.pdf, files.files.markdown, files.files.html].filter(Boolean) as Array<{ path: string }>;
  if (!candidates.length) return true;
  const checks = candidates.slice(0, 2).map(async (f) => {
    const p = String(f.path || '').trim();
    if (!p) return false;
    const lower = p.toLowerCase();
    if (lower.endsWith('.pdf')) {
      const r = await shell.readLocalFile(p);
      return !!r.ok;
    }
    const r = await shell.readLocalText(p);
    return !!r.ok;
  });
  const results = await Promise.all(checks);
  return results.every(Boolean);
}

export async function resolvePaperFiles(
  paperId: string,
  libraryId: string,
  rawPaperId?: string,
): Promise<PaperFiles> {
  const key = cacheKey(paperId, libraryId, rawPaperId);
  const cached = getCachedFiles(key);
  if (cached && await validateCachedFiles(cached)) {
    return cached;
  }

  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';

  const tryFetch = async (id: string): Promise<Response> =>
    fetch(`${API_BASE}/paper/${encodeURIComponent(id)}/files${params}`);

  let resp = await tryFetch(paperId);

  if (resp.status === 404 && rawPaperId && rawPaperId !== paperId) {
    resp = await tryFetch(rawPaperId);
  }

  if (!resp.ok) {
    throw new Error(`failed to resolve paper files: ${resp.status}`);
  }
  const payload = await resp.json();
  const mdPath = String(payload?.files?.markdown?.path || '').trim();
  if (mdPath) {
    const oldPath = getRecordedNotesMarkdownPath(libraryId, paperId);
    if (oldPath && oldPath !== mdPath) {
      await mergeNotesIntoMarkdown(oldPath, mdPath);
    }
    setRecordedNotesMarkdownPath(libraryId, paperId, mdPath);
  }
  setCachedFiles(key, payload);
  return payload;
}

async function electronReadFile(path: string): Promise<Uint8Array | null> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return null;
  const result = await shell.readLocalFile(path);
  if (!result.ok || !result.data) return null;
  const binary = atob(result.data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

async function electronReadText(path: string): Promise<string | null> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return null;
  const result = await shell.readLocalText(path);
  if (!result.ok || !result.data) return null;
  return result.data;
}

export async function loadDocument(
  _paperId: string,
  _libraryId: string,
  files: PaperFiles,
  _rawPaperId?: string,
  preferredType?: 'pdf' | 'markdown' | 'html' | null,
): Promise<{ type: 'pdf' | 'markdown' | 'html' | 'none'; data: Uint8Array | string | null; file_name: string; absolute_path?: string }> {
  const isElectron = window.desktopShell?.runtime === 'electron';
  if (!isElectron) {
    throw new Error('reader_requires_electron_runtime');
  }

  const tryType = async (t: string): Promise<{ type: 'pdf' | 'markdown' | 'html' | 'none'; data: Uint8Array | string | null; file_name: string; absolute_path?: string } | null> => {
    const f = (files.files as Record<string, { path: string; name: string; size_bytes: number } | undefined>)[t];
    if (!f) return null;
    const data = t === 'pdf' ? await electronReadFile(f.path) : await electronReadText(f.path);
    return { type: t as 'pdf' | 'markdown' | 'html', data, file_name: f.name, absolute_path: f.path };
  };

  if (preferredType) {
    const r = await tryType(preferredType);
    if (r) return r;
  }

  for (const t of ['pdf', 'markdown', 'html']) {
    const r = await tryType(t);
    if (r) return r;
  }

  return { type: 'none', data: null, file_name: '', absolute_path: '' };
}
