import type { PaperFiles } from '../../types';

const API_BASE = '';

export async function resolvePaperFiles(
  paperId: string,
  libraryId: string,
): Promise<PaperFiles> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
  const resp = await fetch(`${API_BASE}/paper/${encodeURIComponent(paperId)}/files${params}`);
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
  files: PaperFiles,
): Promise<{ type: 'pdf' | 'markdown' | 'html' | 'none'; data: Uint8Array | string | null; file_name: string }> {
  const isElectron = window.desktopShell?.runtime === 'electron';

  if (files.files.pdf) {
    const f = files.files.pdf;
    const data = isElectron
      ? await electronReadFile(f.path)
      : null;
    return { type: 'pdf', data, file_name: f.name };
  }

  if (files.files.markdown) {
    const f = files.files.markdown;
    const data = isElectron
      ? await electronReadText(f.path)
      : null;
    return { type: 'markdown', data, file_name: f.name };
  }

  if (files.files.html) {
    const f = files.files.html;
    const data = isElectron
      ? await electronReadText(f.path)
      : null;
    return { type: 'html', data, file_name: f.name };
  }

  return { type: 'none', data: null, file_name: '' };
}
