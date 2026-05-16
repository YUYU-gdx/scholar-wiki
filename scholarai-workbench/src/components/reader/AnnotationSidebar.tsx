import { useState, useEffect } from 'react';
import { StickyNote, Trash2, Pencil } from 'lucide-react';
import { notesCache, type NoteEntry } from './NotesCache';
import { deleteNoteFromMarkdownAny, upsertNoteInMarkdown } from './NoteMarkdownSync';

interface AnnotationSidebarProps {
  paperId: string;
  libraryId: string;
  markdownPath?: string;
  isOpen: boolean;
  onToggle: () => void;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return iso;
  }
}

export default function AnnotationSidebar({ paperId, libraryId, markdownPath = '', isOpen, onToggle }: AnnotationSidebarProps) {
  const [readerNotes, setReaderNotes] = useState<NoteEntry[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editComment, setEditComment] = useState('');

  const loadFromFile = () => {
    const shell = window.desktopShell;
    const path = String(markdownPath || '').trim();
    if (!paperId || !path || !shell || shell.runtime !== 'electron') {
      setReaderNotes([]);
      return;
    }
    shell.readLocalText(path).then((res: any) => {
      if (!res?.ok || typeof res.data !== 'string') {
        setReaderNotes([]);
        return;
      }
      const entries = notesCache.load(String(res.data), paperId, libraryId, path);
      setReaderNotes(entries);
    }).catch(() => setReaderNotes([]));
  };

  useEffect(() => {
    if (!paperId) return;
    loadFromFile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, markdownPath]);

  useEffect(() => {
    const handler = (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string }>;
      if (String(e.detail?.paperId || '') !== String(paperId || '')) return;
      loadFromFile();
    };
    window.addEventListener('reader-annotation-changed', handler as EventListener);
    return () => window.removeEventListener('reader-annotation-changed', handler as EventListener);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, markdownPath]);

  const handleDelete = async (entry: NoteEntry) => {
    const path = String(entry.markdownPath || markdownPath || '').trim();
    if (!path) return;
    const res = await deleteNoteFromMarkdownAny([path], entry.id, entry.selectedText, entry.noteText);
    if (res.ok) {
      notesCache.invalidate(paperId);
      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId, noteId: entry.id, action: 'delete' } }));
    }
  };

  const handleEdit = async (entry: NoteEntry) => {
    const path = String(entry.markdownPath || markdownPath || '').trim();
    if (!path) return;
    const hasPdfLocator = entry.pageIndex >= 0 || !!String(entry.rect || '').trim() || !!String(entry.quads || '').trim();
    const ok = await upsertNoteInMarkdown(
      path,
      entry.id,
      entry.selectedText,
      editComment,
      hasPdfLocator ? { pageIndex: entry.pageIndex, rect: entry.rect, quads: entry.quads } : undefined,
    );
    if (!ok) {
      window.alert('保存笔记失败：写入 markdown 失败');
      return;
    }
    notesCache.invalidate(paperId);
    setEditingId(null);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
  };

  const jumpToMarkdownNote = (entry: NoteEntry) => {
    const path = String(entry.markdownPath || markdownPath || '').trim();
    if (!path) return;
    window.dispatchEvent(new CustomEvent('open-reader-file', { detail: { path } }));
    const query = String(entry.selectedText || entry.noteText || '').trim();
    if (query) {
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent('reader-search-and-jump', { detail: { paperId, query } }));
      }, 180);
    }
  };

  const sortedNotes = [...readerNotes].sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));

  return (
    <div className={`border-l border-outline-variant bg-surface-container-lowest flex flex-col transition-all duration-200 ${isOpen ? 'w-80' : 'w-0 overflow-hidden'}`}>
      <div className="px-4 py-3 border-b border-outline-variant flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <StickyNote className="w-4 h-4 text-secondary" />
          <span className="text-sm font-semibold text-on-surface">绗旇</span>
          <span className="text-xs text-on-surface-variant bg-surface-container rounded-full px-2 py-0.5">{readerNotes.length}</span>
        </div>
        <button onClick={onToggle} className="text-sm text-outline hover:text-on-surface leading-none">&times;</button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {sortedNotes.length === 0 && (
          <div className="text-center py-12">
            <StickyNote className="w-8 h-8 text-outline mx-auto mb-2" />
            <p className="text-xs text-on-surface-variant">鏆傛棤绗旇</p>
            <p className="text-xs text-outline mt-1">閫変腑鏂囨湰鍚庡彲娣诲姞绗旇</p>
          </div>
        )}

        {sortedNotes.map((entry) => (
          <div
            key={entry.id}
            className="rounded-xl border border-outline-variant/60 bg-surface-container-low hover:bg-surface-container transition-colors overflow-hidden"
          >
            <div className="flex items-center gap-2 px-3 pt-3 pb-2">
              <span className="inline-flex items-center text-[11px] font-medium rounded-full px-2 py-0.5 bg-secondary-container text-on-secondary-container">
                {entry.pageIndex >= 0 ? `第 ${entry.pageIndex + 1} 页` : 'MD 笔记'}
              </span>
              <div className="ml-auto flex items-center gap-1">
                <button
                  className="text-outline hover:text-secondary p-1 rounded"
                  onClick={() => { setEditingId(editingId === entry.id ? null : entry.id); setEditComment(entry.noteText); }}
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button
                  className="text-outline hover:text-error p-1 rounded"
                  onClick={() => handleDelete(entry)}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <button
              className="w-full text-left px-3 pb-3"
              onClick={() => jumpToMarkdownNote(entry)}
              title="跳转到 markdown 对应位置"
            >
              {entry.selectedText && (
                <div className="mb-2">
                  <p className="text-[11px] text-outline mb-1">引用内容</p>
                  <p className="text-xs leading-relaxed text-on-surface-variant line-clamp-3 pl-2 border-l-2 border-secondary/30">
                    {entry.selectedText}
                  </p>
                </div>
              )}

              <div>
                <p className="text-[11px] text-outline mb-1">绗旇鍐呭</p>
                {editingId === entry.id ? (
                  <div className="space-y-1">
                    <textarea
                      className="w-full text-xs p-2 border border-outline-variant rounded-lg bg-surface-container-lowest resize-none"
                      rows={3}
                      value={editComment}
                      onChange={(e) => setEditComment(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <div className="flex gap-2 justify-end">
                      <button className="text-xs px-3 py-1 rounded-lg bg-primary-container text-on-primary-container font-medium" onClick={(e) => { e.stopPropagation(); handleEdit(entry); }}>保存</button>
                      <button className="text-xs px-3 py-1 rounded-lg text-outline hover:text-on-surface" onClick={(e) => { e.stopPropagation(); setEditingId(null); }}>鍙栨秷</button>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-on-surface leading-relaxed">
                    {entry.noteText || <span className="text-outline italic">（空笔记）</span>}
                  </p>
                )}
              </div>
            </button>

            <div className="px-3 pb-2">
              <span className="text-[10px] text-outline">{formatTime(entry.createdAt)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

