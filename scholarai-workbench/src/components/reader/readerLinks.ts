export const LOCAL_MARKDOWN_ALLOWED_URI_REGEXP = /^(?:(?:https?|file|data|blob):|[a-zA-Z]:[\\/]|\/|#|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i;

export function toFileUrl(absPath: string): string {
  const win = String(absPath || '').replace(/\\/g, '/');
  const withLeading = /^[a-zA-Z]:\//.test(win) ? `/${win}` : win;
  return `file://${encodeURI(withLeading)}`;
}

export function fileUrlToPath(fileUrl: string): string {
  try {
    const u = new URL(fileUrl);
    if (u.protocol !== 'file:') return '';
    const decoded = decodeURIComponent(u.pathname || '');
    if (/^\/[a-zA-Z]:\//.test(decoded)) return decoded.slice(1).replace(/\//g, '\\');
    return decoded;
  } catch {
    return '';
  }
}

export function decodeLinkText(value: string): string {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export function normalizePaperLinkKey(value: string): string {
  return decodeLinkText(value)
    .replace(/^@+/, '')
    .split('#', 1)[0]
    .split('?', 1)[0]
    .replace(/^file:\/+/i, '')
    .split(/[\\/]/)
    .filter(Boolean)
    .pop()!
    .replace(/\.(md|markdown|pdf|html?)$/i, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function validateReaderMarkdownLink(url: string): boolean {
  const raw = String(url || '').trim();
  if (!raw) return true;
  return !/^\s*(?:javascript|vbscript):/i.test(raw);
}

export function resolveMarkdownLinkPath(rawHref: string, markdownAbsolutePath: string): string {
  const raw = String(rawHref || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw) || raw.startsWith('#') || raw.startsWith('data:') || raw.startsWith('blob:')) return '';

  const withoutHash = raw.split('#', 1)[0].trim();
  if (!withoutHash) return '';
  const lower = withoutHash.toLowerCase();
  if (!/\.(md|markdown|html?|pdf)$/.test(lower)) return '';

  if (withoutHash.startsWith('file://')) {
    return fileUrlToPath(withoutHash);
  }
  if (/^[a-zA-Z]:[\\/]/.test(withoutHash) || withoutHash.startsWith('/')) {
    return decodeURIComponent(withoutHash).replace(/\//g, '\\');
  }

  const mdPath = String(markdownAbsolutePath || '').trim();
  if (!mdPath) return '';
  const mdDir = mdPath.replace(/[\\/][^\\/]*$/, '');
  const baseDir = mdDir.endsWith('/') || mdDir.endsWith('\\') ? mdDir : `${mdDir}/`;
  return fileUrlToPath(new URL(withoutHash, toFileUrl(baseDir)).toString());
}
