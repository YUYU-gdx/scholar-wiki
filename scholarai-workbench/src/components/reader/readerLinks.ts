function toFileUrl(absPath: string): string {
  const win = String(absPath || '').replace(/\\/g, '/');
  const withLeading = /^[a-zA-Z]:\//.test(win) ? `/${win}` : win;
  return `file://${encodeURI(withLeading)}`;
}

function fileUrlToPath(fileUrl: string): string {
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

export function resolveMarkdownLinkPath(rawHref: string, markdownAbsolutePath: string): string {
  const raw = String(rawHref || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw) || raw.startsWith('#') || raw.startsWith('data:') || raw.startsWith('blob:')) return '';

  const withoutHash = raw.split('#', 1)[0].trim();
  if (!withoutHash) return '';
  const lower = withoutHash.toLowerCase();
  if (!lower.endsWith('.md') && !lower.endsWith('.markdown')) return '';

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
