import { useState, useEffect } from 'react';
import { Highlighter, Underline, StickyNote, Trash2, Pencil } from 'lucide-react';
import { annotationManager } from './AnnotationManager';
import type { Annotation } from './types';
import { readerNotesManager, type ReaderNoteRecord } from './ReaderNotesManager';
import { deleteNoteFromMarkdownAny, getRecordedNotesMarkdownPath, listRecordedNotesMarkdownPaths, upsertNoteInMarkdown } from './NoteMarkdownSync';

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
  const [readerNotes, setReaderNotes] = useState<ReaderNoteRecord[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editComment, setEditComment] = useState('');
  const [parsedMarkdownNotes, setParsedMarkdownNotes] = useState<ReaderNoteRecord[]>([]);

  useEffect(() => {
    if (!paperId) return;
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
    readerNotesManager.listByPaper(paperId).then(setReaderNotes).catch(() => setReaderNotes([]));
  }, [paperId]);

  useEffect(() => {
    const shell = window.desktopShell;
    const path = String(markdownPath || '').trim();
    if (!paperId || !path || !shell || shell.runtime !== 'electron') {
      setParsedMarkdownNotes([]);
      return;
    }
    shell.readLocalText(path).then((res: any) => {
      if (!res?.ok || typeof res.data !== 'string') {
        setParsedMarkdownNotes([]);
        return;
      }
      const raw = String(res.data || '');
      const blockRe = /> \[!NOTE\] Reader Note[\s\S]*?(?=\n> \[!NOTE\] Reader Note|\n## |\n# |\s*$)/g;
      const matches = raw.match(blockRe) || [];
      const parsed: ReaderNoteRecord[] = matches.map((b, idx) => {
        const id = (b.match(/> Note ID:\s*(.+)/)?.[1] || `md-${idx + 1}`).trim();
        const quote = (b.match(/> Quote:\s*\n>((?:.*\n?)*)\n>\n> Note:/)?.[1] || "")
          .split("\n")
          .map((ln) => ln.replace(/^>\s?/, ""))
          .join("\n")
          .trim();
        const note = (b.match(/> Note:\s*\n>((?:.*\n?)*)\n>\n> Time:/)?.[1] || "")
          .split("\n")
          .map((ln) => ln.replace(/^>\s?/, ""))
          .join("\n")
          .trim();
        const ts = (b.match(/> Time:\s*(.+)/)?.[1] || "").trim();
        return {
          id,
          paper_id: paperId,
          library_id: libraryId,
          doc_type: 'markdown' as const,
          selected_text: quote,
          note_text: note,
          md_anchor: { quote, prefix: "", suffix: "", hash: "" },
          markdown_path_at_write: path,
          page_index: 0,
          created_at: ts || new Date(0).toISOString(),
          updated_at: ts || new Date(0).toISOString(),
        };
      });
      setParsedMarkdownNotes(parsed);
    }).catch(() => setParsedMarkdownNotes([]));
  }, [paperId, markdownPath, readerNotes.length]);

  useEffect(() => {
    const handler = (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string }>;
      if (String(e.detail?.paperId || '') !== String(paperId || '')) return;
      annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
      readerNotesManager.listByPaper(paperId).then(setReaderNotes).catch(() => setReaderNotes([]));
    };
    window.addEventListener('reader-annotation-changed', handler as EventListener);
    return () => window.removeEventListener('reader-annotation-changed', handler as EventListener);
  }, [paperId]);

  const refresh = () => {
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
    readerNotesManager.listByPaper(paperId).then(setReaderNotes).catch(() => setReaderNotes([]));
  };

  const handleDelete = async (id: string) => {
    await annotationManager.remove(id);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
    refresh();
  };

  const resolveMarkdownPath = (notePath?: string): string => {
    const byNote = String(notePath || '').trim();
    if (byNote) return byNote;
    const direct = String(markdownPath || '').trim();
    if (direct) return direct;
    return String(getRecordedNotesMarkdownPath(libraryId, paperId) || '').trim();
  };
  const resolveMarkdownPathCandidates = (notePath?: string): string[] => {
    const direct = String(notePath || '').trim();
    const propPath = String(markdownPath || '').trim();
    const cached = listRecordedNotesMarkdownPaths(libraryId, paperId);
    return Array.from(new Set([direct, propPath, ...cached].filter(Boolean)));
  };

  const removeNoteBlockFromMarkdownById = async (noteId: string, selectedText: string, noteText: string, notePath?: string) => {
    const candidates = resolveMarkdownPathCandidates(notePath);
    // eslint-disable-next-line no-console
    console.log('[notes] sidebar delete candidates', { noteId, candidates });
    const result = await deleteNoteFromMarkdownAny(candidates, noteId, selectedText, noteText);
    void result;
  };

  const updateNoteBlockInMarkdown = async (noteId: string, selectedText: string, noteText: string, notePath?: string) =>
    upsertNoteInMarkdown(resolveMarkdownPath(notePath), noteId, selectedText, noteText);

  const handle保存 = async (id: string) => {
    if (id.startsWith('rn:')) {
      const rid = id.slice(3);
      const row = readerNotes.find((x) => x.id === rid);
      await readerNotesManager.update(rid, editComment);
      if (row) await updateNoteBlockInMarkdown(rid, row.selected_text, editComment, row.markdown_path_at_write);
    } else {
      await annotationManager.update(id, { comment: editComment });
    }
    setEditingId(null);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
    refresh();
  };

  const sorted = [...annotations].filter((a) => a.type !== 'note').sort((a, b) => {
    if (a.page_index !== b.page_index) return a.page_index - b.page_index;
    const aTop = a.rects[0]?.y ?? 0;
    const bTop = b.rects[0]?.y ?? 0;
    return aTop - bTop;
  });
  const mergedReaderNotes = [...readerNotes];
  for (const pn of parsedMarkdownNotes) {
    if (!mergedReaderNotes.some((x) => String(x.id) === String(pn.id))) mergedReaderNotes.push(pn);
  }
  const sortedReaderNotes = [...mergedReaderNotes].sort((a, b) => {
    if (a.page_index !== b.page_index) return a.page_index - b.page_index;
    return String(a.created_at).localeCompare(String(b.created_at));
  });

  return (
    <div className={`border-l border-outline-variant bg-surface-container-lowest flex flex-col transition-all duration-200 ${isOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
      <div className="px-3 py-2 border-b border-outline-variant flex items-center justify-between">
        <span className="text-xs font-mono font-bold text-on-surface uppercase tracking-wider">笔记 ({annotations.length + readerNotes.length})</span>
        <button onClick={onToggle} className="text-xs text-outline hover:text-on-surface">&times;</button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sorted.length === 0 && sortedReaderNotes.length === 0 && (
          <p className="text-xs text-on-surface-variant text-center py-8">暂无标注</p>
        )}
        {sortedReaderNotes.map((rn) => {
          const rowId = `rn:${rn.id}`;
          return (
            <div key={rowId} className="p-2 rounded-lg border border-outline-variant/50 hover:bg-surface-container transition-colors">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-outline"><StickyNote className="w-3.5 h-3.5" /></span>
                <span className="text-[10px] font-mono text-outline">Pg {rn.page_index + 1}</span>
                <button className="ml-auto text-outline hover:text-error" onClick={async () => { await readerNotesManager.remove(rn.id); await removeNoteBlockFromMarkdownById(rn.id, rn.selected_text, rn.note_text, rn.markdown_path_at_write); window.dispatchEvent(new CustomEvent('reader-note-md-deleted', { detail: { paperId, noteId: rn.id } })); window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } })); refresh(); }}>
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              <p className="text-xs text-on-surface line-clamp-2 leading-relaxed">{rn.selected_text}</p>
              {editingId === rowId ? (
                <div className="mt-1">
                  <textarea className="w-full text-xs p-1 border border-outline-variant rounded bg-surface-container" rows={2} value={editComment} onChange={(e) => setEditComment(e.target.value)} />
                  <div className="flex gap-1 mt-1">
                    <button className="text-[10px] px-2 py-0.5 bg-primary-container text-on-primary-container rounded" onClick={() => handle保存(rowId)}>保存</button>
                    <button className="text-[10px] px-2 py-0.5 text-outline" onClick={() => setEditingId(null)}>取消</button>
                  </div>
                </div>
              ) : (
                <button className="text-xs text-secondary mt-1 italic text-left w-full" onClick={() => { setEditingId(rowId); setEditComment(rn.note_text); }}>
                  {rn.note_text || '添加笔记...'}
                </button>
              )}
            </div>
          );
        })}
        {sorted.map((ann) => (
          <div
            key={ann.id}
            className="p-2 rounded-lg border border-outline-variant/50 hover:bg-surface-container cursor-pointer transition-colors"
            onClick={() => onAnnotationClick?.(ann)}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-outline">{typeIcons[ann.type]}</span>
              <span className="text-[10px] font-mono text-outline">Pg {ann.page_index + 1}</span>
              <span
                className="w-3 h-3 rounded-full border border-outline-variant"
                style={{ backgroundColor: ann.color }}
              />
              <button
                className="ml-auto text-outline hover:text-error"
                onClick={(e) => { e.stopPropagation(); handleDelete(ann.id); }}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
            {ann.text && (
              <p className="text-xs text-on-surface line-clamp-2 leading-relaxed">{ann.text}</p>
            )}
            {editingId === ann.id ? (
              <div className="mt-1" onClick={(e) => e.stopPropagation()}>
                <textarea
                  className="w-full text-xs p-1 border border-outline-variant rounded bg-surface-container"
                  rows={2}
                  value={editComment}
                  onChange={(e) => setEditComment(e.target.value)}
                />
                <div className="flex gap-1 mt-1">
                  <button className="text-[10px] px-2 py-0.5 bg-primary-container text-on-primary-container rounded" onClick={() => handle保存(ann.id)}>保存</button>
                  <button className="text-[10px] px-2 py-0.5 text-outline" onClick={() => setEditingId(null)}>取消</button>
                </div>
              </div>
            ) : ann.comment ? (
              <p className="text-xs text-secondary mt-1 italic">{ann.comment}</p>
            ) : (
              <button
                className="text-[10px] text-outline hover:text-secondary mt-1"
                onClick={(e) => { e.stopPropagation(); setEditingId(ann.id); setEditComment(ann.comment); }}
              >
                添加笔记...
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

