import { useState, useEffect } from 'react';
import { Highlighter, Underline, StickyNote, Trash2, Pencil } from 'lucide-react';
import { annotationManager } from './AnnotationManager';
import type { Annotation } from './types';

interface AnnotationSidebarProps {
  paperId: string;
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

export default function AnnotationSidebar({ paperId, isOpen, onToggle, onAnnotationClick }: AnnotationSidebarProps) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editComment, setEditComment] = useState('');

  useEffect(() => {
    if (!paperId) return;
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
  }, [paperId]);

  const refresh = () => {
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
  };

  const handleDelete = async (id: string) => {
    await annotationManager.remove(id);
    refresh();
  };

  const handleSave = async (id: string) => {
    await annotationManager.update(id, { comment: editComment });
    setEditingId(null);
    refresh();
  };

  const sorted = [...annotations].sort((a, b) => {
    if (a.page_index !== b.page_index) return a.page_index - b.page_index;
    const aTop = a.rects[0]?.y ?? 0;
    const bTop = b.rects[0]?.y ?? 0;
    return aTop - bTop;
  });

  return (
    <div className={`border-l border-outline-variant bg-surface-container-lowest flex flex-col transition-all duration-200 ${isOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
      <div className="px-3 py-2 border-b border-outline-variant flex items-center justify-between">
        <span className="text-xs font-mono font-bold text-on-surface uppercase tracking-wider">Annotations ({annotations.length})</span>
        <button onClick={onToggle} className="text-xs text-outline hover:text-on-surface">&times;</button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sorted.length === 0 && (
          <p className="text-xs text-on-surface-variant text-center py-8">No annotations yet</p>
        )}
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
                  <button className="text-[10px] px-2 py-0.5 bg-primary-container text-on-primary-container rounded" onClick={() => handleSave(ann.id)}>Save</button>
                  <button className="text-[10px] px-2 py-0.5 text-outline" onClick={() => setEditingId(null)}>Cancel</button>
                </div>
              </div>
            ) : ann.comment ? (
              <p className="text-xs text-secondary mt-1 italic">{ann.comment}</p>
            ) : (
              <button
                className="text-[10px] text-outline hover:text-secondary mt-1"
                onClick={(e) => { e.stopPropagation(); setEditingId(ann.id); setEditComment(ann.comment); }}
              >
                Add note...
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
