import type { PaperFiles } from '../../types';
const API_BASE = '';

export async function resolvePaperFiles(
  paperId: string,
  libraryId: string,
  rawPaperId?: string,
): Promise<PaperFiles> {
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
  return resp.json();
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
