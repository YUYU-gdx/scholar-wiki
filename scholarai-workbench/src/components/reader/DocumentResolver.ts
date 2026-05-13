// Single entry point: resolve and load a paper's readable file in one step.
// No caching — file system is the source of truth.

export interface ResolvedDocument {
  type: 'pdf' | 'markdown' | 'html' | 'none';
  data: Uint8Array | string | null;
  file_name: string;
  absolute_path: string;
  /** Path to the markdown file when a PDF is the primary loaded type (for note-taking). */
  markdown_path: string;
  /** Path to content_list_v2.json for PDF↔markdown position mapping. */
  content_list_v2_path: string;
}

async function electronReadBinary(path: string): Promise<Uint8Array | null> {
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

export async function resolveAndLoadDocument(
  paperId: string,
  libraryId: string,
  rawPaperId?: string,
  preferredType?: 'pdf' | 'markdown' | 'html' | null,
): Promise<ResolvedDocument> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') {
    throw new Error('reader_requires_electron_runtime');
  }

  // Step 1: get file paths from backend (via Electron main process, no cache)
  let pathsResult = await shell.resolvePaperPaths(paperId, libraryId);
  if (!pathsResult.ok && rawPaperId && rawPaperId !== paperId) {
    pathsResult = await shell.resolvePaperPaths(rawPaperId, libraryId);
  }
  if (!pathsResult.ok) {
    return { type: 'none', data: null, file_name: '', absolute_path: '', markdown_path: '', content_list_v2_path: '' };
  }

  const files = (pathsResult.files || {}) as Record<string, { path: string; name: string; size_bytes: number }>;
  const mdPath = String(files.markdown?.path || '').trim();

  // Step 2: read file content, respecting preferredType
  const order = preferredType
    ? [preferredType, ...['pdf', 'markdown', 'html'].filter(t => t !== preferredType)]
    : ['pdf', 'markdown', 'html'];

  for (const t of order) {
    const f = files[t];
    if (!f?.path) continue;
    if (t === 'pdf') {
      const data = await electronReadBinary(f.path);
      if (data) return { type: 'pdf', data, file_name: f.name, absolute_path: f.path, markdown_path: mdPath, content_list_v2_path: String(pathsResult.content_list_v2_path || '').trim() };
    } else {
      const result = await shell.readLocalText(f.path);
      if (result.ok && result.data != null) {
        return { type: t as 'markdown' | 'html', data: result.data, file_name: f.name, absolute_path: f.path, markdown_path: mdPath, content_list_v2_path: String(pathsResult.content_list_v2_path || '').trim() };
      }
    }
  }

  return { type: 'none', data: null, file_name: '', absolute_path: '', markdown_path: '', content_list_v2_path: '' };
}
