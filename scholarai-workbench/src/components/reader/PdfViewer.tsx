import { useEffect, useMemo, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

interface PdfViewerProps {
  data: Uint8Array;
  fileName: string;
}

function hasValidPdfHeader(data: Uint8Array): boolean {
  if (!data || data.length < 5) return false;
  return data[0] === 0x25 && data[1] === 0x50 && data[2] === 0x44 && data[3] === 0x46 && data[4] === 0x2d;
}

export default function PdfViewer({ data, fileName }: PdfViewerProps) {
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.15);
  const [error, setError] = useState<string | null>(null);
  const safePdfBytes = useMemo(() => Uint8Array.from(data || new Uint8Array()), [data]);
  const validHeader = useMemo(() => hasValidPdfHeader(safePdfBytes), [safePdfBytes]);
  const [pdfUrl, setPdfUrl] = useState<string>('');

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
      </div>
    </div>
  );
}
