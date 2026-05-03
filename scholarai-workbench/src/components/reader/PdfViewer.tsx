import { useEffect, useMemo, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
import SelectionActionPopover from './SelectionActionPopover';
import TranslationModal from './TranslationModal';
import { api } from '../../api';
import { annotationManager } from './AnnotationManager';
import { readerNotesManager } from './ReaderNotesManager';

interface PdfViewerProps {
  data: Uint8Array;
  fileName: string;
  paperId: string;
  libraryId: string;
  markdownPath: string;
}

function hasValidPdfHeader(data: Uint8Array): boolean {
  if (!data || data.length < 5) return false;
  return data[0] === 0x25 && data[1] === 0x50 && data[2] === 0x44 && data[3] === 0x46 && data[4] === 0x2d;
}

export default function PdfViewer({ data, fileName, paperId, libraryId, markdownPath }: PdfViewerProps) {
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.15);
  const [error, setError] = useState<string | null>(null);
  const safePdfBytes = useMemo(() => Uint8Array.from(data || new Uint8Array()), [data]);
  const validHeader = useMemo(() => hasValidPdfHeader(safePdfBytes), [safePdfBytes]);
  const [pdfUrl, setPdfUrl] = useState<string>('');
  const [selectionUI, setSelectionUI] = useState({ visible: false, x: 0, y: 0, text: '' });
  const [translationOpen, setTranslationOpen] = useState(false);
  const [translationText, setTranslationText] = useState('');

  useEffect(() => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[pdf] api_version=', pdfjs.version, 'workerSrc=', pdfjs.GlobalWorkerOptions.workerSrc);
    }
  }, []);

  useEffect(() => {
    const copy = Uint8Array.from(safePdfBytes);
    const blob = new Blob([copy], { type: 'application/pdf' });
    const url = URL.createObjectURL(blob);
    setPdfUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [safePdfBytes]);

  useEffect(() => {
    const onUp = () => {
      const sel = window.getSelection();
      const picked = String(sel?.toString() || '').trim();
      if (!picked || !sel || sel.rangeCount === 0) {
        return;
      }
      const range = sel.getRangeAt(0);
      const containerEl = (range.commonAncestorContainer instanceof Element ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement);
      if (!containerEl?.closest('.react-pdf__Page')) return;
      const rect = range.getBoundingClientRect();
      setSelectionUI({ visible: true, x: Math.max(12, rect.left), y: Math.max(12, rect.bottom + 8), text: picked });
    };
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mouseup', onUp);
    };
  }, []);

  const appendMdNoteByAnchor = async (selectedText: string, noteText: string) => {
    if (!markdownPath || window.desktopShell?.runtime !== 'electron') return;
    const read = await window.desktopShell.readLocalText(markdownPath);
    if (!read.ok || !read.data) return;
    const raw = read.data;
    const idx = raw.indexOf(selectedText);
    const now = new Date().toISOString();
    const block = `\n\n> [!NOTE] Reader Note\n> 引用：\n> ${selectedText}\n>\n> 笔记：\n> ${noteText}\n>\n> 时间：\n> ${now}\n`;
    let next = '';
    if (idx >= 0) {
      const tail = raw.slice(idx);
      const endInTail = tail.search(/\n\s*\n/);
      const insertAt = endInTail >= 0 ? idx + endInTail : raw.length;
      next = `${raw.slice(0, insertAt)}${block}${raw.slice(insertAt)}`;
    } else {
      next = `${raw}\n\n## Reader Notes${block}`;
    }
    await window.desktopShell.writeLocalText(markdownPath, next);
  };

  const handleTranslate = async () => {
    try {
      const cfg = await api.chat.getTranslationProviderConfig();
      const result = await api.chat.translate(selectionUI.text, cfg);
      setTranslationText(result.translated_text || '');
      setTranslationOpen(true);
    } catch (e) {
      setTranslationText(`翻译失败：${(e as Error).message}`);
      setTranslationOpen(true);
    }
  };

  const handleSaveNote = async (note: string) => {
    const anchor = readerNotesManager.makeAnchor(selectionUI.text, selectionUI.text);
    await readerNotesManager.add({
      paper_id: paperId,
      library_id: libraryId,
      doc_type: 'pdf',
      page_index: currentPage - 1,
      selected_text: selectionUI.text,
      note_text: note,
      md_anchor: anchor,
    });
    await annotationManager.add({
      paper_id: paperId,
      library_id: libraryId,
      type: 'note',
      page_index: currentPage - 1,
      rects: [],
      text: selectionUI.text,
      comment: note,
      color: '#f59e0b',
      ink_paths: [],
      linked_node_ids: [],
    });
    await appendMdNoteByAnchor(selectionUI.text, note);
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
    setSelectionUI((p) => ({ ...p, visible: false }));
  };

  const pdfDocumentNode = useMemo(() => (
    <Document
      key={pdfUrl || fileName}
      file={pdfUrl}
      onLoadSuccess={(pdf) => {
        setPageCount(pdf.numPages);
        setCurrentPage(1);
        setError(null);
      }}
      onLoadError={(e) => setError(`Failed to load PDF: ${e.message}`)}
      loading={<div className="text-sm text-on-surface-variant">Loading PDF...</div>}
      error={<div className="text-sm text-error">{error || 'Failed to load PDF.'}</div>}
    >
      <Page
        pageNumber={currentPage}
        scale={scale}
        renderTextLayer
        renderAnnotationLayer
      />
    </Document>
  ), [pdfUrl, fileName, currentPage, scale, error]);

  if (!validHeader) {
    return (
      <div className="flex flex-col h-full bg-surface-container-low">
        <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
          <span className="text-xs font-mono text-on-surface-variant truncate max-w-[300px]">{fileName}</span>
        </div>
        <div className="flex-1 overflow-auto flex items-center justify-center p-4">
          <div className="text-sm text-error">文件不是合法 PDF（文件头缺少 %PDF- 标识）</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-surface-container-low">
      <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <span className="text-xs font-mono text-on-surface-variant truncate max-w-[300px]">{fileName}</span>
        <div className="flex items-center gap-3">
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container disabled:opacity-30"
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          >
            Prev
          </button>
          <span className="text-xs font-mono">{currentPage} / {pageCount || '-'}</span>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container disabled:opacity-30"
            disabled={pageCount <= 0 || currentPage >= pageCount}
            onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => Math.round((s + 0.15) * 100) / 100)}
          >
            Zoom {Math.round(scale * 100)}%
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => Math.max(0.6, Math.round((s - 0.15) * 100) / 100))}
          >
            Out
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto flex justify-center p-4">
        {pdfDocumentNode}
      </div>
      <SelectionActionPopover
        visible={selectionUI.visible}
        x={selectionUI.x}
        y={selectionUI.y}
        selectedText={selectionUI.text}
        onTranslate={handleTranslate}
        onSaveNote={handleSaveNote}
        onClose={() => { setSelectionUI((p) => ({ ...p, visible: false })); }}
      />
      <TranslationModal open={translationOpen} text={translationText} onClose={() => setTranslationOpen(false)} />
    </div>
  );
}
