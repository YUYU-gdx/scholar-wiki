import { useEffect, useState } from 'react';
import { Languages } from 'lucide-react';

interface SelectionActionPopoverProps {
  visible: boolean;
  x: number;
  y: number;
  selectedText: string;
  onTranslate: () => Promise<void> | void;
  onSaveNote: (note: string) => Promise<void> | void;
  translationText?: string;
  translationLoading?: boolean;
  onClose: () => void;
}

export default function SelectionActionPopover({
  visible,
  x,
  y,
  selectedText,
  onTranslate,
  onSaveNote,
  translationText = '',
  translationLoading = false,
  onClose,
}: SelectionActionPopoverProps) {
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setNote('');
    setSaving(false);
  }, [selectedText, visible]);

  if (!visible) return null;

  return (
    <div
      style={{ left: x, top: y }}
      className="selection-action-popover fixed z-50 w-[380px] max-w-[90vw] rounded-xl border border-outline-variant bg-surface-container-lowest shadow-2xl p-3 space-y-2"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-[11px] text-on-surface-variant line-clamp-2">{selectedText}</div>
        <button className="text-[10px] px-1.5 py-0.5 rounded border border-outline-variant hover:bg-surface-container" onClick={onClose}>关闭</button>
      </div>
      <div className="flex items-center gap-2">
        <button onClick={onTranslate} className="px-3 py-1.5 rounded-lg border border-outline-variant hover:bg-surface-container inline-flex items-center gap-1 text-xs">
          <Languages className="w-3.5 h-3.5" />
          翻译
        </button>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="输入笔记..."
          className="flex-1 px-2 py-1.5 rounded border border-outline-variant bg-surface-container text-xs"
        />
        <button
          onClick={async () => {
            if (!note.trim() || saving) return;
            setSaving(true);
            try {
              await onSaveNote(note);
            } finally {
              setSaving(false);
            }
          }}
          disabled={!note.trim() || saving}
          className="px-3 py-1.5 rounded-lg bg-secondary text-on-secondary disabled:opacity-50 text-xs"
        >
          {saving ? '保存中...' : '保存笔记'}
        </button>
      </div>
      {(translationLoading || translationText) && (
        <div className="rounded border border-outline-variant bg-surface-container p-2 text-xs leading-relaxed whitespace-pre-wrap max-h-44 overflow-auto">
          {translationLoading ? '翻译中...' : translationText}
        </div>
      )}
    </div>
  );
}
