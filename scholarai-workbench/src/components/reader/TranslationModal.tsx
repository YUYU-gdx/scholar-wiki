interface TranslationModalProps {
  open: boolean;
  text: string;
  onClose: () => void;
}

export default function TranslationModal({ open, text, onClose }: TranslationModalProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/35 flex items-center justify-center" onClick={onClose}>
      <div className="w-[680px] max-w-[94vw] rounded-2xl border border-outline-variant bg-surface-container-lowest p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="text-sm font-semibold mb-3">翻译结果</div>
        <div className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-sm leading-relaxed text-on-surface">{text}</div>
        <div className="mt-4 flex justify-end">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-outline-variant hover:bg-surface-container text-xs">关闭</button>
        </div>
      </div>
    </div>
  );
}

