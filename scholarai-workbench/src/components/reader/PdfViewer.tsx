import { useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
import SelectionActionPopover from './SelectionActionPopover';
import { api } from '../../api';
import { ensureMarkdownPathForNotes, mergeNotesIntoMarkdown, setRecordedNotesMarkdownPath, upsertNoteInMarkdown } from './NoteMarkdownSync';
import { loadContentList, findTouchedBlocks, getBlocksQuote } from './ContentListResolver';
import type { ContentBlock } from './ContentListResolver';
import type { PaperFiles } from '../../types';
import { isSelectionInside } from './selectionScope';

interface PdfViewerProps {
  data: Uint8Array;
  fileName: string;
  paperId: string;
  libraryId: string;
  markdownPath: string;
  sourcePath: string;
  contentListV2Path: string;
}

function hasValidPdfHeader(data: Uint8Array): boolean {
  if (!data || data.length < 5) return false;
  return data[0] === 0x25 && data[1] === 0x50 && data[2] === 0x44 && data[3] === 0x46 && data[4] === 0x2d;
}

export default function PdfViewer({ data, fileName, paperId, libraryId, markdownPath, sourcePath, contentListV2Path }: PdfViewerProps) {
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.15);
  const [error, setError] = useState<string | null>(null);
  const safePdfBytes = useMemo(() => Uint8Array.from(data || new Uint8Array()), [data]);
  const validHeader = useMemo(() => hasValidPdfHeader(safePdfBytes), [safePdfBytes]);
  const [pdfUrl, setPdfUrl] = useState<string>('');
  const [selectionUI, setSelectionUI] = useState({ visible: false, x: 0, y: 0, text: '', pageIndex: -1 });
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationText, setTranslationText] = useState('');
  const selectionHostRef = useRef<HTMLDivElement>(null);
  const [pdfDocProxy, setPdfDocProxy] = useState<any>(null);
  const pageTextCacheRef = useRef<Map<number, string>>(new Map());
  const contentListRef = useRef<ContentBlock[][] | null>(null);
  const contentListLoadedRef = useRef(false);

  useEffect(() => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[pdf] api_version=', pdfjs.version, 'workerSrc=', pdfjs.GlobalWorkerOptions.workerSrc);
    }
  }, []);

  useEffect(() => {
    const flash = (el: HTMLElement) => {
      const prev = el.style.backgroundColor;
      const prevTransition = el.style.transition;
      el.style.transition = 'background-color 180ms ease';
      el.style.backgroundColor = 'rgba(251, 191, 36, 0.28)';
      window.setTimeout(() => {
        el.style.backgroundColor = prev;
        el.style.transition = prevTransition;
      }, 1400);
    };
    const onJump = async (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string; query?: string }>;
      if (String(e.detail?.paperId || '').trim() !== String(paperId || '').trim()) return;
      const q = String(e.detail?.query || '').replace(/\s+/g, ' ').trim();
      if (!q || !pdfDocProxy) return;
      const candidates = (() => {
        const out: string[] = [];
        out.push(q);
        const sentence = q.split(/[.;:!?。；：！？]/)[0]?.trim();
        if (sentence && sentence.length >= 12) out.push(sentence);
        const words = q.split(/\s+/).filter(Boolean);
        if (words.length >= 8) out.push(words.slice(0, 8).join(' '));
        if (words.length >= 5) out.push(words.slice(0, 5).join(' '));
        return Array.from(new Set(out.map((x) => x.toLowerCase())));
      })();
      try {
        const getPageText = async (p: number) => {
          if (pageTextCacheRef.current.has(p)) return String(pageTextCacheRef.current.get(p) || '');
          const page = await pdfDocProxy.getPage(p);
          const tc = await page.getTextContent();
          const joined = (tc.items || []).map((it: any) => String(it.str || '')).join(' ').replace(/\s+/g, ' ').toLowerCase();
          pageTextCacheRef.current.set(p, joined);
          return joined;
        };
        let targetPage = -1;
        const currentText = await getPageText(currentPage);
        if (candidates.some((c) => currentText.includes(c))) {
          targetPage = currentPage;
        }
        for (let p = 1; targetPage < 0 && p <= Number(pdfDocProxy.numPages || 0); p += 1) {
          const joined = await getPageText(p);
          if (candidates.some((c) => joined.includes(c))) {
            targetPage = p;
            break;
          }
        }
        if (targetPage < 0) return;
        setCurrentPage(targetPage);
        window.setTimeout(() => {
          const host = selectionHostRef.current;
          if (!host) return;
          const spans = Array.from(host.querySelectorAll('.react-pdf__Page__textContent span')) as HTMLElement[];
          const hit = spans.find((s) => {
            const txt = String(s.textContent || '').replace(/\s+/g, ' ').toLowerCase();
            return candidates.some((c) => txt.includes(c));
          });
          if (!hit) return;
          hit.scrollIntoView({ behavior: 'smooth', block: 'center' });
          flash(hit);
        }, 220);
      } catch {
        // silent no-op
      }
    };
    window.addEventListener('reader-search-and-jump', onJump as EventListener);
    return () => window.removeEventListener('reader-search-and-jump', onJump as EventListener);
  }, [paperId, pdfDocProxy]);

  useEffect(() => {
    const copy = Uint8Array.from(safePdfBytes);
    const blob = new Blob([copy], { type: 'application/pdf' });
    const url = URL.createObjectURL(blob);
    pageTextCacheRef.current.clear();
    setPdfUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [safePdfBytes]);

  // Load content_list_v2.json for PDF↔markdown position mapping
  useEffect(() => {
    if (!contentListV2Path || contentListLoadedRef.current) return;
    let cancelled = false;
    loadContentList(contentListV2Path).then((pages) => {
      if (cancelled) return;
      contentListRef.current = pages;
      contentListLoadedRef.current = true;
      // eslint-disable-next-line no-console
      console.log('[pdf] content_list_v2 loaded', { path: contentListV2Path, pages: pages.length });
    });
    return () => { cancelled = true; };
  }, [contentListV2Path]);

  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host) return;
    const onUp = () => {
      const sel = window.getSelection();
      if (!isSelectionInside(host, sel)) {
        setSelectionUI((prev) => (prev.visible ? { ...prev, visible: false } : prev));
        return;
      }
      const picked = String(sel?.toString() || '').trim();
      if (!picked || !sel || sel.rangeCount === 0) {
        setSelectionUI((prev) => (prev.visible ? { ...prev, visible: false } : prev));
        return;
      }
      const range = sel.getRangeAt(0);
      const containerEl = (range.commonAncestorContainer instanceof Element ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement);
      const pageEl = containerEl?.closest('.react-pdf__Page') as HTMLElement | null;
      if (!pageEl) return;
      const pageNumberAttr = pageEl?.getAttribute('data-page-number');
      const pageIndex = pageNumberAttr ? parseInt(pageNumberAttr, 10) - 1 : -1;
      const rect = range.getBoundingClientRect();
      setSelectionUI({ visible: true, x: Math.max(12, rect.left), y: Math.max(12, rect.top - 220), text: picked, pageIndex });
      setTranslationText('');
    };
    host.addEventListener('mouseup', onUp);
    return () => {
      host.removeEventListener('mouseup', onUp);
    };
  }, []);

  const appendMdNoteByAnchor = async (noteId: string, selectedText: string, noteText: string): Promise<string> => {
    if (markdownPath) setRecordedNotesMarkdownPath(libraryId, paperId, markdownPath);
    const filesStub: PaperFiles = {
      paper_id: paperId,
      library_id: libraryId,
      files: {
        markdown: markdownPath ? { path: markdownPath, name: 'markdown.md', size_bytes: 0 } : undefined,
        pdf: undefined,
        html: undefined,
      },
      default_view: 'markdown',
      content_list_v2_path: contentListV2Path,
    };
    // supply one existing path to derive directory when markdown is missing
    if (!filesStub.files.markdown && sourcePath) {
      filesStub.files.pdf = { path: sourcePath, name: fileName, size_bytes: 0 };
    }
    const ensured = await ensureMarkdownPathForNotes(filesStub, paperId);
    if (!ensured) return '';
    if (markdownPath && ensured && markdownPath !== ensured) {
      await mergeNotesIntoMarkdown(markdownPath, ensured);
    }
    setRecordedNotesMarkdownPath(libraryId, paperId, ensured);
    await upsertNoteInMarkdown(ensured, noteId, selectedText, noteText);
    return ensured;
  };

  const handleTranslate = async () => {
    try {
      setTranslationLoading(true);
      const cfg = await api.chat.getTranslationProviderConfig();
      const result = await api.chat.translate(selectionUI.text, cfg);
      setTranslationText(result.translated_text || '');
    } catch (e) {
      setTranslationText(`Translation failed: ${(e as Error).message}`);
    } finally {
      setTranslationLoading(false);
    }
  };

  const handleSaveNote = async (note: string) => {
    const noteText = String(note || '').trim();
    const picked = String(selectionUI.text || '').trim();
    if (!noteText || !picked) return;

    const noteId = crypto.randomUUID();
    const pageIndex = selectionUI.pageIndex;
    // eslint-disable-next-line no-console
    console.log('[notes] pdf save start', { noteId, paperId, libraryId, pickedLen: picked.length, noteLen: noteText.length, pageIndex });

    try {
      const contentPages = contentListRef.current;

      // ── Block-based quote: expand selection to full blocks, clean, then match like case 1 ──
      let quote = picked;
      if (contentPages && pageIndex >= 0 && pageIndex < contentPages.length) {
        const pageBlocks = contentPages[pageIndex];
        const touched = findTouchedBlocks(pageBlocks, picked);
        if (touched) {
          const full = getBlocksQuote(pageBlocks, touched.startIdx, touched.endIdx);
          // Clean: strip leading/trailing whitespace/newlines, normalize inner whitespace
          const cleaned = full.quote.replace(/^[\s\n\r]+|[\s\n\r]+$/g, '').replace(/\s+/g, ' ').trim();
          if (cleaned) {
            quote = cleaned;
            // eslint-disable-next-line no-console
            console.log('[notes] block quote expanded', { pageIndex, startIdx: touched.startIdx, endIdx: touched.endIdx, origLen: picked.length, quoteLen: quote.length });
          }
        }
      }

      // ── Standard path: same as case 1 (MD manual selection) ──
      const ensuredPath = await appendMdNoteByAnchor(noteId, quote, noteText);
      // eslint-disable-next-line no-console
      console.log('[notes] pdf save done', { ensuredPath, quoteLen: quote.length });
      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
      setSelectionUI((p) => ({ ...p, visible: false }));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[notes] pdf save failed', e);
      window.alert(`保存笔记失败：${(e as Error).message}`);
    }
  };

  const pdfDocumentNode = useMemo(() => (
    <Document
      key={pdfUrl || fileName}
      file={pdfUrl}
      onLoadSuccess={(pdf) => {
        setPdfDocProxy(pdf as any);
        setPageCount(pdf.numPages);
        setCurrentPage(1);
        setError(null);
      }}
      onLoadError={(e) => setError(`Failed to load PDF: ${e.message}`)}
      loading={<div className="text-sm text-on-surface-variant">Loading PDF...</div>}
      error={<div className="text-sm text-error">{error || 'Failed to load PDF.'}</div>}
    >
      {Array.from({ length: pageCount || 0 }, (_, i) => (
        <Page
          key={`page_${i + 1}`}
          pageNumber={i + 1}
          scale={scale}
          renderTextLayer
          renderAnnotationLayer
        />
      ))}
    </Document>
  ), [pdfUrl, fileName, pageCount, scale, error]);

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
          <span className="text-xs font-mono">{pageCount || '-'} pages</span>
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

      <div ref={selectionHostRef} className="flex-1 overflow-auto flex justify-center p-4">
        {pdfDocumentNode}
      </div>
      <SelectionActionPopover
        visible={selectionUI.visible}
        x={selectionUI.x}
        y={selectionUI.y}
        selectedText={selectionUI.text}
        onTranslate={handleTranslate}
        onSaveNote={handleSaveNote}
        translationText={translationText}
        translationLoading={translationLoading}
        onClose={() => { setSelectionUI((p) => ({ ...p, visible: false })); }}
      />
    </div>
  );
}
