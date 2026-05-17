import type { TabDescriptor } from './types';

export function inferReaderTypeFromPath(path: string): TabDescriptor['type'] {
  const lower = String(path || '').toLowerCase().split(/[?#]/, 1)[0];
  if (lower.endsWith('.pdf')) return 'pdf';
  if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html';
  return 'markdown';
}

export function fileNameFromPath(path: string): string {
  const clean = String(path || '').split(/[?#]/, 1)[0];
  return clean.split(/[\\/]/).filter(Boolean).pop() || clean || 'Document';
}

export function createFileReaderTab(path: string, libraryId: string): TabDescriptor | null {
  const cleanPath = String(path || '').trim();
  if (!cleanPath) return null;
  return {
    id: crypto.randomUUID(),
    paperId: `file:${cleanPath}`,
    libraryId,
    type: inferReaderTypeFromPath(cleanPath),
    path: cleanPath,
    title: fileNameFromPath(cleanPath),
  };
}

export function createPaperReaderTab(paperId: string, libraryId: string, type: TabDescriptor['type'] = 'markdown'): TabDescriptor | null {
  const cleanPaperId = String(paperId || '').trim();
  const cleanLibraryId = String(libraryId || '').trim();
  if (!cleanPaperId || !cleanLibraryId) return null;
  return {
    id: crypto.randomUUID(),
    paperId: cleanPaperId,
    libraryId: cleanLibraryId,
    type,
    path: '',
    title: cleanPaperId,
  };
}

export function isFileReaderTab(tab: Pick<TabDescriptor, 'paperId' | 'path'>): boolean {
  return String(tab.paperId || '').startsWith('file:') && !!String(tab.path || '').trim();
}
