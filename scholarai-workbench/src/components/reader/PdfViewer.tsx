import { useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
import SelectionActionPopover from './SelectionActionPopover';
import { api } from '../../api';
import { upsertNoteInMarkdown } from './NoteMarkdownSync';
import { loadContentList, findTouchedBlocks, getBlocksQuote, computeUnionBbox } from './ContentListResolver';
import type { ContentBlock } from './ContentListResolver';
import { isSelectionInside } from './selectionScope';
import { notesCache } from './NotesCache';

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
  const [highlights, setHighlights] = useState<Array<{ pageIndex: number; x0: number; y0: number; x1: number; y1: number; noteId: string }>>([]);
  const pageDimsRef = useRef<Map<number, { width: number; height: number }>>(new Map());
  const highlightsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [floatingNote, setFloatingNote] = useState<{ visible: boolean; noteText: string; quote: string; x: number; y: number }>({ visible: false, noteText: '', quote: '', x: 0, y: 0 });
  const floatingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Load page dimensions and note highlights whenever notes change
  const loadHighlights = async () => {
    if (!pdfDocProxy || !markdownPath) return;
    try {
      // Fetch page dimensions (lazy, one page at a time)
      const dims = pageDimsRef.current;
      if (dims.size === 0) {
        const firstPage = await pdfDocProxy.getPage(1);
        const vp = firstPage.getViewport({ scale: 1 });
        dims.set(1, { width: vp.width, height: vp.height });
      }
      // Load notes from the main markdown file
      const shell = window.desktopShell;
      if (!shell || shell.runtime !== 'electron' || !markdownPath) return;
      const res = await shell.readLocalText(markdownPath);
      if (!res.ok || !res.data) return;
      const entries = notesCache.load(String(res.data), paperId, libraryId, markdownPath);
      const hls: Array<{ pageIndex: number; x0: number; y0: number; x1: number; y1: number; noteId: string }> = [];
      for (const e of entries) {
        if (!e.rect) continue;
        const parts = e.rect.split(',').map(Number);
        if (parts.length === 4 && parts.every((n) => !isNaN(n))) {
          hls.push({ pageIndex: e.pageIndex, x0: parts[0], y0: parts[1], x1: parts[2], y1: parts[3], noteId: e.id });
        }
      }
      setHighlights(hls);
      // eslint-disable-next-line no-console
      console.log('[pdf] highlights loaded', { count: hls.length });
    } catch {
      // silent
    }
  };

  useEffect(() => {
    loadHighlights();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDocProxy, markdownPath]);

  useEffect(() => {
    const handler = () => {
      // Debounce — notes might not be written to disk yet
      if (highlightsTimerRef.current) clearTimeout(highlightsTimerRef.current);
      highlightsTimerRef.current = setTimeout(() => loadHighlights(), 300);
    };
    window.addEventListener('reader-annotation-changed', handler);
    return () => {
      window.removeEventListener('reader-annotation-changed', handler);
      if (highlightsTimerRef.current) clearTimeout(highlightsTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDocProxy, markdownPath]);

  const appendMdNoteByAnchor = async (noteId: string, selectedText: string, noteText: string, opts?: { pageIndex?: number; rect?: string }): Promise<string> => {
    if (!markdownPath) return '';
    await upsertNoteInMarkdown(markdownPath, noteId, selectedText, noteText, { pageIndex: opts?.pageIndex, rect: opts?.rect });
    return markdownPath;
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
      let noteOpts: { pageIndex?: number; rect?: string } | undefined;
      if (contentPages && pageIndex >= 0 && pageIndex < contentPages.length) {
        const pageBlocks = contentPages[pageIndex];
        const touched = findTouchedBlocks(pageBlocks, picked);
        if (touched) {
          const full = getBlocksQuote(pageBlocks, touched.startIdx, touched.endIdx);
          // Compute union bbox of all touched blocks for highlight positioning
          const unionBbox = computeUnionBbox(pageBlocks, touched.startIdx, touched.endIdx);
          // eslint-disable-next-line no-console
          console.log('[notes] raw quote from blocks', {
            rawLen: full.quote.length,
            rawHead: full.quote.slice(0, 120),
            rawTail: full.quote.slice(-80),
            unionBbox,
          });
          // Clean: strip leading/trailing whitespace/newlines, normalize inner whitespace
          const cleaned = full.quote.replace(/^[\s\n\r]+|[\s\n\r]+$/g, '').replace(/\s+/g, ' ').trim();
          if (cleaned) {
            // eslint-disable-next-line no-console
            console.log('[notes] cleaned quote', {
              cleanedLen: cleaned.length,
              cleanedHead: cleaned.slice(0, 120),
              cleanedTail: cleaned.slice(-80),
            });
            quote = cleaned;
            noteOpts = { pageIndex, rect: unionBbox ? `${unionBbox.x0},${unionBbox.y0},${unionBbox.x1},${unionBbox.y1}` : undefined };
          } else {
            // eslint-disable-next-line no-console
            console.log('[notes] cleaned quote was empty, falling back to picked');
          }
        } else {
          // eslint-disable-next-line no-console
          console.log('[notes] findTouchedBlocks returned null, falling back to picked');
        }
      } else {
        // eslint-disable-next-line no-console
        console.log('[notes] no content_list_v2 available, using picked text', { hasPages: !!contentPages, pageIndex, pageCount: contentPages?.length });
      }

      // ── Standard path: same as case 1 (MD manual selection) ──
      const ensuredPath = await appendMdNoteByAnchor(noteId, quote, noteText, noteOpts);
      // eslint-disable-next-line no-console
      console.log('[notes] pdf save done', { ensuredPath, quoteLen: quote.length });

      // Show floating note card next to the highlight
      if (noteOpts?.rect && noteOpts.pageIndex != null) {
        const host = selectionHostRef.current;
        if (host) {
          // Delay to let React render highlights first
          setTimeout(() => {
            const pageEl = host.querySelector(`[data-page-number="${noteOpts.pageIndex! + 1}"]`) as HTMLElement | null;
            if (pageEl) {
              const highlight = pageEl.querySelector('.kn-pdf-highlight') as HTMLElement | null;
              if (highlight) {
                const hr = highlight.getBoundingClientRect();
                setFloatingNote({
                  visible: true,
                  noteText,
                  quote: quote.slice(0, 200),
                  x: hr.right + 12,
                  y: hr.top,
                });
                // Auto-dismiss after 6s
                if (floatingTimerRef.current) clearTimeout(floatingTimerRef.current);
                floatingTimerRef.current = setTimeout(() => {
                  setFloatingNote((p) => ({ ...p, visible: false }));
                }, 6000);
              }
            }
          }, 200);
        }
      }

      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
      setSelectionUI((p) => ({ ...p, visible: false }));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[notes] pdf save failed', e);
      window.alert(`保存笔记失败：${(e as Error).message}`);
    }
  };

  // ── Render highlight overlays on PDF pages ──
  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host) return;

    const renderHighlights = () => {
      // Remove old highlight containers
      host.querySelectorAll('.kn-pdf-highlight-layer').forEach((el) => el.remove());

      if (highlights.length === 0) return;

      const defaultDims = pageDimsRef.current.get(1) || { width: 612, height: 792 };

      // Group highlights by page
      const byPage = new Map<number, typeof highlights>();
      for (const h of highlights) {
        const list = byPage.get(h.pageIndex) || [];
        list.push(h);
        byPage.set(h.pageIndex, list);
      }

      for (const [pageIdx, hls] of byPage) {
        const pageEl = host.querySelector(`[data-page-number="${pageIdx + 1}"]`) as HTMLElement | null;
        if (!pageEl) continue;

        // Get page dimensions for this page (lazy, use default if unknown)
        let dims = pageDimsRef.current.get(pageIdx + 1);
        if (!dims) {
          // Use a reasonable default same as first page
          dims = defaultDims;
        }

        const layer = document.createElement('div');
        layer.className = 'kn-pdf-highlight-layer';
        layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:5;';

        for (const h of hls) {
          const el = document.createElement('div');
          el.className = 'kn-pdf-highlight';
          const left = (h.x0 / dims.width) * 100;
          const top = ((dims.height - h.y1) / dims.height) * 100;
          const w = ((h.x1 - h.x0) / dims.width) * 100;
          const hgt = ((h.y1 - h.y0) / dims.height) * 100;
          el.style.cssText = `position:absolute;left:${left}%;top:${top}%;width:${w}%;height:${hgt}%;background:rgba(251,191,36,0.25);border-radius:2px;pointer-events:auto;cursor:pointer;transition:background 0.15s;`;
          el.title = '笔记标注';
          el.addEventListener('mouseenter', () => {
            el.style.background = 'rgba(251,191,36,0.45)';
          });
          el.addEventListener('mouseleave', () => {
            el.style.background = 'rgba(251,191,36,0.25)';
          });
          layer.appendChild(el);
        }

        // Position relative to the page's canvas wrapper
        const canvasWrapper = pageEl.querySelector('.react-pdf__Page__canvas') as HTMLElement | null;
        if (canvasWrapper) {
          canvasWrapper.style.position = 'relative';
          canvasWrapper.appendChild(layer);
        } else {
          // Fallback: append to page element itself, but make it relative
          const prevPos = pageEl.style.position;
          if (!prevPos || prevPos === 'static') pageEl.style.position = 'relative';
          pageEl.appendChild(layer);
        }
      }
    };

    // Delay to allow React to finish rendering pages
    const timer = setTimeout(renderHighlights, 150);
    return () => clearTimeout(timer);
  }, [highlights, scale, pageCount]);

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

        {/* Floating note card after saving */}
        {floatingNote.visible && (
          <div
            className="fixed z-50 max-w-[320px] rounded-xl border border-outline-variant bg-surface-container-lowest shadow-2xl p-4 space-y-2"
            style={{ left: `${floatingNote.x}px`, top: `${floatingNote.y}px` }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-secondary">笔记已保存</span>
              <button
                className="text-outline hover:text-on-surface text-sm leading-none"
                onClick={() => {
                  setFloatingNote((p) => ({ ...p, visible: false }));
                  if (floatingTimerRef.current) clearTimeout(floatingTimerRef.current);
                }}
              >
                &times;
              </button>
            </div>
            {floatingNote.quote && (
              <p className="text-xs text-on-surface-variant line-clamp-3 leading-relaxed pl-2 border-l-2 border-secondary/30">
                {floatingNote.quote}
              </p>
            )}
            <p className="text-xs text-on-surface leading-relaxed">{floatingNote.noteText}</p>
          </div>
        )}
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
