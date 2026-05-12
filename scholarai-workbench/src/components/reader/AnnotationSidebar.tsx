import { useState, useEffect } from 'react';
import { Highlighter, Underline, StickyNote, Trash2, Pencil } from 'lucide-react';
import { annotationManager } from './AnnotationManager';
import type { Annotation } from './types';
import { notesCache, type NoteEntry } from './NotesCache';
import { deleteNoteFromMarkdownAny, upsertNoteInMarkdown } from './NoteMarkdownSync';

interface AnnotationSidebarProps {
  paperId: string;
  libraryId: string;
  markdownPath?: string;
  isOpen: boolean;
  onToggle: () => void;
  onAnnotationClick?: (annotation: Annotation) => void;
}

const typeIcons: Record<string, React.ReactNode> = {
  highlight: <Highlighter className="w-3.5 h-3.5" />,
  underline: <Underline className="w-3.5 h-3.5" />,
  note: <StickyNote className="w-3.5 h-3.5" />,
  ink: <Pencil className="w-3.5 h-3.5" />,
};

export default function AnnotationSidebar({ paperId, libraryId, markdownPath = '', isOpen, onToggle, onAnnotationClick }: AnnotationSidebarProps) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [readerNotes, setReaderNotes] = useState<NoteEntry[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editComment, setEditComment] = useState('');

  const loadFromFile = () => {
    const shell = window.desktopShell;
    const path = String(markdownPath || '').trim();
    if (!paperId || !path || !shell || shell.runtime !== 'electron') {
      setReaderNotes(notesCache.get(paperId));
      return;
    }
    shell.readLocalText(path).then((res: any) => {
      if (!res?.ok || typeof res.data !== 'string') {
        setReaderNotes(notesCache.get(paperId));
        return;
      }
      const entries = notesCache.load(String(res.data), paperId, libraryId, path);
      setReaderNotes(entries);
    }).catch(() => setReaderNotes(notesCache.get(paperId)));
  };

  useEffect(() => {
    if (!paperId) return;
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
    loadFromFile();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, markdownPath]);

  useEffect(() => {
    const handler = (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string }>;
      if (String(e.detail?.paperId || '') !== String(paperId || '')) return;
      annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
      loadFromFile();
    };
    window.addEventListener('reader-annotation-changed', handler as EventListener);
    return () => window.removeEventListener('reader-annotation-changed', handler as EventListener);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, markdownPath]);

  const handleDelete = async (id: string) => {
    await annotationManager.remove(id);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
  };

  const handleReaderNoteDelete = async (entry: NoteEntry) => {
    const path = String(entry.markdownPath || markdownPath || '').trim();
    if (!path) return;
    const ok = await deleteNoteFromMarkdownAny([path], entry.id, entry.selectedText, entry.noteText);
    if (ok) {
      notesCache.invalidate(paperId);
      window.dispatchEvent(new CustomEvent('reader-note-md-deleted', { detail: { paperId, noteId: entry.id } }));
      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
    }
  };

  const handleReaderNoteEdit = async (entry: NoteEntry) => {
    const path = String(entry.markdownPath || markdownPath || '').trim();
    if (!path) return;
    await upsertNoteInMarkdown(path, entry.id, entry.selectedText, editComment);
    notesCache.invalidate(paperId);
    setEditingId(null);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
  };

  const handleAnnotationEdit = async (id: string) => {
    await annotationManager.update(id, { comment: editComment });
    setEditingId(null);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
  };

  const sortedAnnotations = [...annotations].filter((a) => a.type !== 'note').sort((a, b) => {
    if (a.page_index !== b.page_index) return a.page_index - b.page_index;
    return (a.rects[0]?.y ?? 0) - (b.rects[0]?.y ?? 0);
  });

  const sortedReaderNotes = [...readerNotes].sort((a, b) =>
    String(a.createdAt).localeCompare(String(b.createdAt)),
  );

  return (
    <div className={`border-l border-outline-variant bg-surface-container-lowest flex flex-col transition-all duration-200 ${isOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
      <div className="px-3 py-2 border-b border-outline-variant flex items-center justify-between">
        <span className="text-xs font-mono font-bold text-on-surface uppercase tracking-wider">笔记 ({sortedAnnotations.length + sortedReaderNotes.length})</span>
        <button onClick={onToggle} className="text-xs text-outline hover:text-on-surface">&times;</button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sortedAnnotations.length === 0 && sortedReaderNotes.length === 0 && (
          <p className="text-xs text-on-surface-variant text-center py-8">暂无标注</p>
        )}

        {sortedReaderNotes.map((rn) => (
          <div key={rn.id} className="p-2 rounded-lg border border-outline-variant/50 hover:bg-surface-container transition-colors">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-outline"><StickyNote className="w-3.5 h-3.5" /></span>
              <span className="text-xs font-mono text-outline">Pg {rn.pageIndex + 1}</span>
              <button className="ml-auto text-outline hover:text-error" onClick={() => handleReaderNoteDelete(rn)}>
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
            <p className="text-xs text-on-surface line-clamp-2 leading-relaxed">{rn.selectedText}</p>
            {editingId === rn.id ? (
              <div className="mt-1">
                <textarea className="w-full text-xs p-1 border border-outline-variant rounded bg-surface-container" rows={2} value={editComment} onChange={(e) => setEditComment(e.target.value)} />
                <div className="flex gap-1 mt-1">
                  <button className="text-xs px-2 py-0.5 bg-primary-container text-on-primary-container rounded" onClick={() => handleReaderNoteEdit(rn)}>保存</button>
                  <button className="text-xs px-2 py-0.5 text-outline" onClick={() => setEditingId(null)}>取消</button>
                </div>
              </div>
            ) : (
              <button className="text-xs text-secondary mt-1 italic text-left w-full" onClick={() => { setEditingId(rn.id); setEditComment(rn.noteText); }}>
                {rn.noteText || '添加笔记...'}
              </button>
            )}
          </div>
        ))}

        {sortedAnnotations.map((ann) => (
          <div
            key={ann.id}
            className="p-2 rounded-lg border border-outline-variant/50 hover:bg-surface-container cursor-pointer transition-colors"
            onClick={() => onAnnotationClick?.(ann)}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-outline">{typeIcons[ann.type]}</span>
              <span className="text-xs font-mono text-outline">Pg {ann.page_index + 1}</span>
              <span className="w-3 h-3 rounded-full border border-outline-variant" style={{ backgroundColor: ann.color }} />
              <button className="ml-auto text-outline hover:text-error" onClick={(e) => { e.stopPropagation(); handleDelete(ann.id); }}>
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
            {ann.text && <p className="text-xs text-on-surface line-clamp-2 leading-relaxed">{ann.text}</p>}
            {editingId === ann.id ? (
              <div className="mt-1" onClick={(e) => e.stopPropagation()}>
                <textarea className="w-full text-xs p-1 border border-outline-variant rounded bg-surface-container" rows={2} value={editComment} onChange={(e) => setEditComment(e.target.value)} />
                <div className="flex gap-1 mt-1">
                  <button className="text-xs px-2 py-0.5 bg-primary-container text-on-primary-container rounded" onClick={() => handleAnnotationEdit(ann.id)}>保存</button>
                  <button className="text-xs px-2 py-0.5 text-outline" onClick={() => setEditingId(null)}>取消</button>
                </div>
              </div>
            ) : ann.comment ? (
              <p className="text-xs text-secondary mt-1 italic">{ann.comment}</p>
            ) : (
              <button className="text-xs text-outline hover:text-secondary mt-1" onClick={(e) => { e.stopPropagation(); setEditingId(ann.id); setEditComment(ann.comment); }}>添加笔记...</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
