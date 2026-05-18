import { useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
import SelectionActionPopover from './SelectionActionPopover';
import { api } from '../../api';
import { upsertNoteInMarkdown } from './NoteMarkdownSync';
import { isSelectionInside } from './selectionScope';
import { notesCache } from './NotesCache';
import { buildReaderPositionKey, readReaderPosition, writeReaderPosition } from './ReaderPositionStore';

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
  const [selectionUI, setSelectionUI] = useState<{
    visible: boolean;
    x: number;
    y: number;
    text: string;
    pageIndex: number;
    normRects?: Array<{ x0: number; y0: number; x1: number; y1: number }>;
  }>({ visible: false, x: 0, y: 0, text: '', pageIndex: -1 });
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationText, setTranslationText] = useState('');
  const selectionHostRef = useRef<HTMLDivElement>(null);
  const [pdfDocProxy, setPdfDocProxy] = useState<any>(null);
  const pageTextCacheRef = useRef<Map<number, string>>(new Map());
  const [highlights, setHighlights] = useState<Array<{ pageIndex: number; noteId: string; rects: Array<{ x0: number; y0: number; x1: number; y1: number }> }>>([]);
  const pageDimsRef = useRef<Map<number, { width: number; height: number }>>(new Map());
  const highlightsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [noteMeta, setNoteMeta] = useState<Map<string, { pageIndex: number; noteText: string; quote: string }>>(new Map());
  const [noteCards, setNoteCards] = useState<Array<{ noteId: string; x: number; y: number; noteText: string; quote: string }>>([]);
  const clampScale = (value: number): number => Math.max(0.6, Math.min(3.0, Math.round(value * 100) / 100));
  const readerPositionKey = useMemo(() => buildReaderPositionKey({
    libraryId,
    paperId,
    absolutePath: sourcePath,
    viewerType: 'pdf',
  }), [libraryId, paperId, sourcePath]);

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

  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host) return;

    const applyZoomDelta = (delta: number) => {
      setScale((s) => clampScale(s + delta));
    };

    const onWheel = (evt: WheelEvent) => {
      if (!(evt.ctrlKey || evt.metaKey)) return;
      evt.preventDefault();
      applyZoomDelta(evt.deltaY < 0 ? 0.1 : -0.1);
    };

    const onKeyDown = (evt: KeyboardEvent) => {
      if (!(evt.ctrlKey || evt.metaKey)) return;
      const key = String(evt.key || '').toLowerCase();
      if (key === '=' || key === '+') {
        evt.preventDefault();
        applyZoomDelta(0.15);
        return;
      }
      if (key === '-' || key === '_') {
        evt.preventDefault();
        applyZoomDelta(-0.15);
        return;
      }
      if (key === '0') {
        evt.preventDefault();
        setScale(1.15);
      }
    };

    host.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('keydown', onKeyDown);
    return () => {
      host.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);


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
      let normRects: Array<{ x0: number; y0: number; x1: number; y1: number }> | undefined;
      const canvasEl = pageEl.querySelector('.react-pdf__Page__canvas') as HTMLElement | null;
      if (canvasEl) {
        const cr = canvasEl.getBoundingClientRect();
        if (cr.width > 0 && cr.height > 0) {
          const clamp01 = (n: number) => Math.max(0, Math.min(1, n));
          const rangeRects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
          const srcRects = rangeRects.length > 0 ? rangeRects : [rect];
          normRects = srcRects.map((r) => {
            const x0 = clamp01((r.left - cr.left) / cr.width);
            const y0 = clamp01((r.top - cr.top) / cr.height);
            const x1 = clamp01((r.right - cr.left) / cr.width);
            const y1 = clamp01((r.bottom - cr.top) / cr.height);
            return { x0: Math.min(x0, x1), y0: Math.min(y0, y1), x1: Math.max(x0, x1), y1: Math.max(y0, y1) };
          }).filter((r) => (r.x1 - r.x0) > 0.0005 && (r.y1 - r.y0) > 0.0005);
        }
      }
      setSelectionUI({ visible: true, x: Math.max(12, rect.left), y: Math.max(12, rect.top - 220), text: picked, pageIndex, normRects });
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
      // Load notes from the main markdown file
      const shell = window.desktopShell;
      if (!shell || shell.runtime !== 'electron' || !markdownPath) return;
      const res = await shell.readLocalText(markdownPath);
      if (!res.ok || !res.data) return;
      const entries = notesCache.load(String(res.data), paperId, libraryId, markdownPath);
      const hls: Array<{ pageIndex: number; noteId: string; rects: Array<{ x0: number; y0: number; x1: number; y1: number }> }> = [];
      for (const e of entries) {
        const rects: Array<{ x0: number; y0: number; x1: number; y1: number }> = [];
        const quadGroups = String(e.quads || '').split('|').map((g) => g.trim()).filter(Boolean);
        for (const g of quadGroups) {
          const p = g.split(',').map(Number);
          if (p.length === 4 && p.every((n) => !isNaN(n))) rects.push({ x0: p[0], y0: p[1], x1: p[2], y1: p[3] });
        }
        if (rects.length === 0 && e.rect) {
          const parts = e.rect.split(',').map(Number);
          if (parts.length === 4 && parts.every((n) => !isNaN(n))) rects.push({ x0: parts[0], y0: parts[1], x1: parts[2], y1: parts[3] });
        }
        if (rects.length > 0) {
          hls.push({ pageIndex: e.pageIndex, noteId: e.id, rects });
          if (!pageDimsRef.current.has(e.pageIndex + 1)) {
            // eslint-disable-next-line no-await-in-loop
            const page = await pdfDocProxy.getPage(e.pageIndex + 1);
            const vp = page.getViewport({ scale: 1 });
            pageDimsRef.current.set(e.pageIndex + 1, { width: vp.width, height: vp.height });
          }
        }
      }
      setHighlights(hls);
      const highlightIdSet = new Set(hls.map((h) => String(h.noteId || '')));
      const nextMeta = new Map<string, { pageIndex: number; noteText: string; quote: string }>();
      for (const e of entries) {
        const id = String(e.id || '');
        if (!id || !highlightIdSet.has(id)) continue;
        nextMeta.set(id, {
          pageIndex: Number(e.pageIndex || 0),
          noteText: String(e.noteText || ''),
          quote: String(e.selectedText || '').slice(0, 220),
        });
      }
      setNoteMeta(nextMeta);
    } catch {
      // silent
    }
  };

  useEffect(() => {
    loadHighlights();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDocProxy, markdownPath]);

  useEffect(() => {
    const handler = (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string; noteId?: string; action?: string }>;
      if (String(e.detail?.paperId || '') && String(e.detail?.paperId || '') !== String(paperId || '')) return;
      const deletedNoteId = String(e.detail?.action || '') === 'delete' ? String(e.detail?.noteId || '') : '';
      if (deletedNoteId) {
        setHighlights((prev) => prev.filter((h) => String(h.noteId || '') !== deletedNoteId));
        setNoteMeta((prev) => {
          const next = new Map(prev);
          next.delete(deletedNoteId);
          return next;
        });
        setNoteCards((prev) => prev.filter((c) => c.noteId !== deletedNoteId));
      }
      if (highlightsTimerRef.current) clearTimeout(highlightsTimerRef.current);
      highlightsTimerRef.current = setTimeout(() => loadHighlights(), 300);
    };
    window.addEventListener('reader-annotation-changed', handler as EventListener);
    return () => {
      window.removeEventListener('reader-annotation-changed', handler as EventListener);
      if (highlightsTimerRef.current) clearTimeout(highlightsTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDocProxy, markdownPath, paperId]);

  const appendMdNoteByAnchor = async (
    noteId: string,
    selectedText: string,
    noteText: string,
    opts?: { pageIndex?: number; rect?: string; quads?: string; anchorText?: string },
  ): Promise<{ ok: boolean; path: string }> => {
    if (!markdownPath) return { ok: false, path: '' };
    const ok = await upsertNoteInMarkdown(markdownPath, noteId, selectedText, noteText, {
      pageIndex: opts?.pageIndex,
      rect: opts?.rect,
      quads: opts?.quads,
      anchorText: opts?.anchorText,
    });
    return { ok, path: markdownPath };
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

    try {
      const quote = picked;
      let noteOpts: { pageIndex?: number; rect?: string; quads?: string; anchorText?: string } | undefined;

      // Derive PDF rects from current selection geometry.
      if (pageIndex >= 0 && selectionUI.normRects && selectionUI.normRects.length > 0 && pdfDocProxy) {
        try {
          let dims = pageDimsRef.current.get(pageIndex + 1);
          if (!dims) {
            const pg = await pdfDocProxy.getPage(pageIndex + 1);
            const vp = pg.getViewport({ scale: 1 });
            dims = { width: vp.width, height: vp.height };
            pageDimsRef.current.set(pageIndex + 1, dims);
          }
          const pdfRects = selectionUI.normRects.map((nr) => {
            const x0 = nr.x0 * dims.width;
            const x1 = nr.x1 * dims.width;
            const y1 = (1 - nr.y0) * dims.height;
            const y0 = (1 - nr.y1) * dims.height;
            return { x0, y0, x1, y1 };
          });
          const rect = pdfRects.reduce((acc, r) => ({
            x0: Math.min(acc.x0, r.x0),
            y0: Math.min(acc.y0, r.y0),
            x1: Math.max(acc.x1, r.x1),
            y1: Math.max(acc.y1, r.y1),
          }));
          noteOpts = {
            pageIndex,
            rect: `${rect.x0},${rect.y0},${rect.x1},${rect.y1}`,
            quads: pdfRects.map((r) => `${r.x0},${r.y0},${r.x1},${r.y1}`).join('|'),
            anchorText: picked,
          };
        } catch {
          // no-op
        }
      }

      // 鈹€鈹€ Standard path: same as case 1 (MD manual selection) 鈹€鈹€
      const ensured = await appendMdNoteByAnchor(noteId, quote, noteText, noteOpts);
      if (!ensured.ok) {
        throw new Error('笔记写入 markdown 失败，请确认 markdown 路径和读写权限');
      }

      setNoteMeta((prev) => {
        const next = new Map(prev);
        next.set(noteId, { pageIndex, noteText, quote: quote.slice(0, 220) });
        return next;
      });

      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
      setSelectionUI((p) => ({ ...p, visible: false }));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[notes] pdf save failed', e);
      window.alert(`保存笔记失败：${(e as Error).message}`);
    }
  };

  // 鈹€鈹€ Render highlight overlays on PDF pages 鈹€鈹€
  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host) return;

    const renderHighlights = () => {
      // Remove old highlight containers
      host.querySelectorAll('.kn-pdf-highlight-layer').forEach((el) => el.remove());

      if (highlights.length === 0) return;

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
        const dims = pageDimsRef.current.get(pageIdx + 1);
        if (!dims) continue;

        const layer = document.createElement('div');
        layer.className = 'kn-pdf-highlight-layer';
        layer.style.cssText = 'position:absolute;pointer-events:none;z-index:5;';

        for (const h of hls) {
          for (const r of h.rects) {
            const el = document.createElement('div');
            el.className = 'kn-pdf-highlight';
            el.setAttribute('data-note-id', String(h.noteId || ''));
            const left = (r.x0 / dims.width) * 100;
            const top = ((dims.height - r.y1) / dims.height) * 100;
            const w = ((r.x1 - r.x0) / dims.width) * 100;
            const hgt = ((r.y1 - r.y0) / dims.height) * 100;
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
        }
        // Position the overlay against the rendered canvas box.
        const canvasEl = pageEl.querySelector('.react-pdf__Page__canvas') as HTMLElement | null;
        if (canvasEl) {
          const prevPos = pageEl.style.position;
          if (!prevPos || prevPos === 'static') pageEl.style.position = 'relative';
          layer.style.left = `${canvasEl.offsetLeft}px`;
          layer.style.top = `${canvasEl.offsetTop}px`;
          layer.style.width = `${canvasEl.clientWidth}px`;
          layer.style.height = `${canvasEl.clientHeight}px`;
          pageEl.appendChild(layer);
        } else {
          layer.style.left = '0';
          layer.style.top = '0';
          layer.style.right = '0';
          layer.style.bottom = '0';
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

  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host) {
      setNoteCards([]);
      return;
    }
    const recompute = () => {
      const hostRect = host.getBoundingClientRect();
      const cards: Array<{ noteId: string; x: number; y: number; noteText: string; quote: string }> = [];
      const cardX = host.scrollLeft + Math.max(12, host.clientWidth - 340);
      for (const [noteId, meta] of noteMeta.entries()) {
        const pageEl = host.querySelector(`[data-page-number="${meta.pageIndex + 1}"]`) as HTMLElement | null;
        if (!pageEl) continue;
        const hit = pageEl.querySelector(`.kn-pdf-highlight[data-note-id="${noteId}"]`) as HTMLElement | null;
        if (!hit) continue;
        const hr = hit.getBoundingClientRect();
        cards.push({
          noteId,
          x: cardX,
          y: (hr.top - hostRect.top) + host.scrollTop,
          noteText: meta.noteText,
          quote: meta.quote,
        });
      }
      setNoteCards(cards);
    };
    recompute();
    host.addEventListener('scroll', recompute, { passive: true });
    window.addEventListener('resize', recompute);
    return () => {
      host.removeEventListener('scroll', recompute);
      window.removeEventListener('resize', recompute);
    };
  }, [noteMeta, highlights, scale, pageCount]);

  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host || !pageCount) return;
    const saved = readReaderPosition(readerPositionKey);
    if (!saved) return;
    const apply = () => {
      if (Number.isFinite(saved.scrollTop)) {
        host.scrollTop = saved.scrollTop || 0;
        host.scrollLeft = saved.scrollLeft || 0;
        return;
      }
      if (saved.pageNumber) {
        const pageEl = host.querySelector(`.react-pdf__Page[data-page-number="${saved.pageNumber}"]`) as HTMLElement | null;
        pageEl?.scrollIntoView({ block: 'start' });
      }
    };
    const raf = window.requestAnimationFrame(() => {
      apply();
      window.requestAnimationFrame(apply);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [pageCount, pdfUrl, readerPositionKey]);

  useEffect(() => {
    const host = selectionHostRef.current;
    if (!host) return;
    let timer: number | null = null;
    const save = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const hostRect = host.getBoundingClientRect();
        const pages = Array.from(host.querySelectorAll('.react-pdf__Page')) as HTMLElement[];
        const visible = pages
          .map((pageEl) => {
            const rect = pageEl.getBoundingClientRect();
            return {
              pageEl,
              distance: Math.abs(rect.top - hostRect.top),
            };
          })
          .sort((a, b) => a.distance - b.distance)[0]?.pageEl;
        const pageNumber = Number(visible?.getAttribute('data-page-number') || currentPage || 1);
        writeReaderPosition(readerPositionKey, {
          scrollTop: host.scrollTop,
          scrollLeft: host.scrollLeft,
          pageNumber,
        });
        if (Number.isFinite(pageNumber) && pageNumber > 0) setCurrentPage(pageNumber);
      }, 120);
    };
    host.addEventListener('scroll', save, { passive: true });
    return () => {
      host.removeEventListener('scroll', save);
      if (timer !== null) window.clearTimeout(timer);
      writeReaderPosition(readerPositionKey, {
        scrollTop: host.scrollTop,
        scrollLeft: host.scrollLeft,
        pageNumber: currentPage,
      });
    };
  }, [currentPage, readerPositionKey]);

  const pdfDocumentNode = useMemo(() => (
    <Document
      key={pdfUrl || fileName}
      file={pdfUrl}
      onLoadSuccess={(pdf) => {
        const saved = readReaderPosition(readerPositionKey);
        setPdfDocProxy(pdf as any);
        setPageCount(pdf.numPages);
        setCurrentPage(saved?.pageNumber || 1);
        setError(null);
        pageDimsRef.current.clear();
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
  ), [pdfUrl, fileName, pageCount, scale, error, readerPositionKey]);

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
    <div className="relative flex flex-col h-full bg-surface-container-low">
      <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <span className="text-xs font-mono text-on-surface-variant truncate max-w-[300px]">{fileName}</span>
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono">{pageCount || '-'} pages</span>
          <span
            className="text-[11px] text-on-surface-variant"
            title="Ctrl/Cmd + Wheel, Ctrl/Cmd + +/-, Ctrl/Cmd + 0"
          >
            Ctrl/Cmd + Wheel
          </span>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => clampScale(s - 0.15))}
            title="Zoom out (Ctrl/Cmd + -)"
          >
            -
          </button>
          <span className="text-xs font-mono min-w-[52px] text-center">{Math.round(scale * 100)}%</span>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => clampScale(s + 0.15))}
            title="Zoom in (Ctrl/Cmd + +)"
          >
            +
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale(1.15)}
            title="Reset zoom (Ctrl/Cmd + 0)"
          >
            100%
          </button>
        </div>
      </div>

      <div ref={selectionHostRef} className="relative flex-1 overflow-auto flex justify-center p-4 md:pr-[22rem]">
        {pdfDocumentNode}

        {noteCards.map((card) => (
          <div
            key={card.noteId}
            className="absolute z-40 w-[320px] max-w-[30vw] rounded-xl border border-outline-variant bg-surface-container-lowest shadow-2xl p-4 space-y-2"
            style={{ left: `${card.x}px`, top: `${card.y}px` }}
          >
            <p className="text-xs text-on-surface leading-relaxed whitespace-pre-wrap">
              {card.noteText}
            </p>
          </div>
        ))}
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

