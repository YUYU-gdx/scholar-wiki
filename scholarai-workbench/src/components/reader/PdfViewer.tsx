import { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfViewerProps {
  data: Uint8Array;
  fileName: string;
  onSelection?: (text: string, rects: { x: number; y: number; width: number; height: number; page: number }[]) => void;
}

export default function PdfViewer({ data, fileName, onSelection }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const loadingTask = pdfjsLib.getDocument({ data });
    loadingTask.promise.then((pdf) => {
      if (cancelled) return;
      pdfDocRef.current = pdf;
      setPageCount(pdf.numPages);
      setCurrentPage(1);
      setLoading(false);
    }).catch((e) => {
      if (cancelled) return;
      setError(`Failed to load PDF: ${e.message}`);
      setLoading(false);
    });

    return () => {
      cancelled = true;
      loadingTask.destroy().catch(() => {});
    };
  }, [data]);

  useEffect(() => {
    if (!pdfDocRef.current || !containerRef.current) return;
    let cancelled = false;

    pdfDocRef.current.getPage(currentPage).then((page) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const container = containerRef.current!;
      container.innerHTML = '';

      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.display = 'block';
      canvas.style.margin = '0 auto';
      container.appendChild(canvas);

      const ctx = canvas.getContext('2d')!;
      page.render({ canvasContext: ctx, viewport }).promise.then(() => {
        if (cancelled) return;

        const textLayerDiv = document.createElement('div');
        textLayerDiv.className = 'textLayer';
        textLayerDiv.style.position = 'absolute';
        textLayerDiv.style.left = '0';
        textLayerDiv.style.top = '0';
        textLayerDiv.style.width = `${viewport.width}px`;
        textLayerDiv.style.height = `${viewport.height}px`;
        container.style.position = 'relative';
        container.appendChild(textLayerDiv);

        page.getTextContent().then((textContent) => {
          if (cancelled || !textLayerDiv) return;
          const textLayer = new pdfjsLib.TextLayer({
            textContentSource: textContent,
            container: textLayerDiv,
            viewport,
          });
          textLayer.render();
        });
      });
    });

    return () => { cancelled = true; };
  }, [currentPage, scale]);

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
          <span className="text-xs font-mono">{currentPage} / {pageCount}</span>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container disabled:opacity-30"
            disabled={currentPage >= pageCount}
            onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => Math.round((s + 0.2) * 10) / 10)}
          >
            Zoom {Math.round(scale * 100)}%
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => Math.max(0.5, Math.round((s - 0.2) * 10) / 10))}
          >
            Out
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto flex justify-center p-4">
        {loading && <div className="text-sm text-on-surface-variant self-center">Loading PDF...</div>}
        {error && <div className="text-sm text-error self-center">{error}</div>}
        <div ref={containerRef} />
      </div>
    </div>
  );
}
