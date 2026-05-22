export interface ReaderChatSessionRef {
  libraryId: string;
  paperId: string;
  sessionId: string;
}

const MARKER = 'scholar-wiki-reader-chat-session';
const SESSION_COMMENT_RE = /<!--\s*scholar-wiki-reader-chat-session\s+({[\s\S]*?})\s*-->/g;

function normalizeId(value: string): string {
  return String(value || '').trim();
}

function normalizeNewlines(value: string): string {
  return String(value || '').replace(/\r\n/g, '\n');
}

export function extractReaderChatSessionRef(markdown: string, libraryId: string, paperId: string): ReaderChatSessionRef | null {
  const targetLibraryId = normalizeId(libraryId);
  const targetPaperId = normalizeId(paperId);
  if (!targetLibraryId || !targetPaperId) return null;

  const matches = Array.from(normalizeNewlines(markdown).matchAll(SESSION_COMMENT_RE));
  for (let i = matches.length - 1; i >= 0; i -= 1) {
    try {
      const row = JSON.parse(matches[i][1] || '{}') as Partial<ReaderChatSessionRef>;
      const rowLibraryId = normalizeId(row.libraryId || '');
      const rowPaperId = normalizeId(row.paperId || '');
      const sessionId = normalizeId(row.sessionId || '');
      if (rowLibraryId === targetLibraryId && rowPaperId === targetPaperId && sessionId) {
        return { libraryId: rowLibraryId, paperId: rowPaperId, sessionId };
      }
    } catch {
      // Ignore malformed historical comments.
    }
  }
  return null;
}

export function upsertReaderChatSessionRef(markdown: string, ref: ReaderChatSessionRef): string {
  const libraryId = normalizeId(ref.libraryId);
  const paperId = normalizeId(ref.paperId);
  const sessionId = normalizeId(ref.sessionId);
  if (!libraryId || !paperId || !sessionId) return normalizeNewlines(markdown);

  const src = normalizeNewlines(markdown);
  const kept = src.replace(SESSION_COMMENT_RE, (full, json) => {
    try {
      const row = JSON.parse(String(json || '{}')) as Partial<ReaderChatSessionRef>;
      if (normalizeId(row.libraryId || '') === libraryId && normalizeId(row.paperId || '') === paperId) {
        return '';
      }
    } catch {
      // Keep malformed comments for manual recovery.
    }
    return full;
  }).replace(/[ \t]+\n/g, '\n').replace(/\n{4,}$/g, '\n\n');

  const payload = JSON.stringify({ libraryId, paperId, sessionId });
  const comment = `<!-- ${MARKER} ${payload} -->`;
  const trimmed = kept.replace(/\s*$/, '');
  return `${trimmed}${trimmed ? '\n\n' : ''}${comment}\n`;
}

export async function readReaderChatSessionRef(markdownPath: string, libraryId: string, paperId: string): Promise<ReaderChatSessionRef | null> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) return null;
  const read = await shell.readLocalText(markdownPath);
  if (!read.ok) return null;
  return extractReaderChatSessionRef(read.data || '', libraryId, paperId);
}

export async function writeReaderChatSessionRef(markdownPath: string, ref: ReaderChatSessionRef): Promise<boolean> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron' || !markdownPath) return false;
  const read = await shell.readLocalText(markdownPath);
  if (!read.ok) return false;
  const next = upsertReaderChatSessionRef(read.data || '', ref);
  const wrote = await shell.writeLocalText(markdownPath, next);
  return !!wrote.ok;
}
