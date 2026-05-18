const READER_POSITION_PREFIX = 'kn_graph_reader_position_v1';

export interface ReaderPositionKeyParts {
  libraryId: string;
  paperId: string;
  absolutePath: string;
  viewerType: 'markdown' | 'pdf';
}

export interface ReaderPosition {
  scrollTop?: number;
  scrollLeft?: number;
  pageNumber?: number;
  updatedAt?: number;
}

function normalizePart(value: string): string {
  return String(value || '').trim().replace(/\\/g, '/').toLowerCase();
}

export function buildReaderPositionKey(parts: ReaderPositionKeyParts): string {
  const libraryId = normalizePart(parts.libraryId);
  const paperId = normalizePart(parts.paperId);
  const absolutePath = normalizePart(parts.absolutePath);
  const identity = absolutePath || `${libraryId}:${paperId}`;
  return `${READER_POSITION_PREFIX}:${parts.viewerType}:${libraryId}:${identity}`;
}

export function readReaderPosition(key: string): ReaderPosition | null {
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ReaderPosition;
    return {
      scrollTop: Number.isFinite(parsed.scrollTop) ? Math.max(0, Number(parsed.scrollTop)) : undefined,
      scrollLeft: Number.isFinite(parsed.scrollLeft) ? Math.max(0, Number(parsed.scrollLeft)) : undefined,
      pageNumber: Number.isFinite(parsed.pageNumber) ? Math.max(1, Number(parsed.pageNumber)) : undefined,
      updatedAt: Number.isFinite(parsed.updatedAt) ? Number(parsed.updatedAt) : undefined,
    };
  } catch {
    return null;
  }
}

export function writeReaderPosition(key: string, position: ReaderPosition): void {
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify({
      scrollTop: Number.isFinite(position.scrollTop) ? Math.max(0, Number(position.scrollTop)) : 0,
      scrollLeft: Number.isFinite(position.scrollLeft) ? Math.max(0, Number(position.scrollLeft)) : 0,
      pageNumber: Number.isFinite(position.pageNumber) ? Math.max(1, Number(position.pageNumber)) : undefined,
      updatedAt: Date.now(),
    }));
  } catch {
    // localStorage may be unavailable in restricted contexts.
  }
}
