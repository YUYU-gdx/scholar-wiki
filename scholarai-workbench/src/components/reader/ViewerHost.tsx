import { useState, useEffect } from 'react';
import { FileText, AlertCircle } from 'lucide-react';
import PdfViewer from './PdfViewer';
import MarkdownEditor from './MarkdownEditor';
import AnnotationSidebar from './AnnotationSidebar';
import ReaderChatSidebar from './ReaderChatSidebar';
import { resolveAndLoadDocument, type ResolvedDocument } from './DocumentResolver';

interface ViewerHostProps {
  paperId: string;
  libraryId: string;
  preferredType?: 'pdf' | 'markdown' | 'html' | null;
  rawPaperId?: string;
  onDocumentMeta?: (meta: { absolutePath: string; fileName: string; type: 'pdf' | 'markdown' | 'html' | 'none' }) => void;
}

export default function ViewerHost({ paperId, libraryId, preferredType, rawPaperId, onDocumentMeta }: ViewerHostProps) {
  const [document, setDocument] = useState<ResolvedDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    if (!paperId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    resolveAndLoadDocument(paperId, libraryId, rawPaperId, preferredType)
      .then((doc) => {
        if (cancelled) return;
        setDocument(doc);
        onDocumentMeta?.({
          absolutePath: doc.absolute_path || '',
          fileName: doc.file_name || '',
          type: doc.type,
        });
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e.message);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [paperId, libraryId, preferredType, rawPaperId, onDocumentMeta]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-low">
        <div className="text-center space-y-3">
          <FileText className="w-8 h-8 text-outline animate-pulse mx-auto" />
          <p className="text-sm text-on-surface-variant">Loading document...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-low">
        <div className="text-center space-y-3">
          <AlertCircle className="w-8 h-8 text-error mx-auto" />
          <p className="text-sm text-error">{error}</p>
        </div>
      </div>
    );
  }

  if (!document || document.type === 'none') {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-low">
        <div className="text-center space-y-3">
          <FileText className="w-8 h-8 text-outline mx-auto" />
          <p className="text-sm text-on-surface-variant">No readable file available for this paper.</p>
          <p className="text-xs text-outline">{paperId}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex overflow-hidden relative">
      <div className="flex-1 flex flex-col overflow-hidden">
        {document.type === 'pdf' && document.data instanceof Uint8Array && (
          <PdfViewer
            data={document.data}
            fileName={document.file_name}
            paperId={paperId}
            libraryId={libraryId}
            markdownPath={String(document.markdown_path || '')}
            sourcePath={String(document.absolute_path || '')}
          />
        )}
        {document.type === 'markdown' && typeof document.data === 'string' && (
          <MarkdownEditor
            paperId={paperId}
            libraryId={libraryId}
            content={document.data}
            fileName={document.file_name}
            absolutePath={String(document.absolute_path || '')}
          />
        )}
        {document.type === 'html' && typeof document.data === 'string' && (
          <div className="flex-1 overflow-auto p-6 bg-surface-container-lowest">
            <div className="max-w-[800px] mx-auto p-4 border border-outline-variant rounded-xl bg-surface-container-low text-sm text-on-surface-variant">
              HTML 阅读器已临时封存。请优先使用 PDF 或 Markdown。
            </div>
          </div>
        )}
      </div>

      {(document.type === 'pdf' || document.type === 'markdown') && (
        <AnnotationSidebar
          paperId={paperId}
          libraryId={libraryId}
          markdownPath={String(document.markdown_path || '')}
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
        />
      )}

      {!sidebarOpen && (document.type === 'pdf' || document.type === 'markdown') && (
        <button
          className="absolute right-4 top-16 px-2 py-1 text-[10px] font-mono bg-surface-container border border-outline-variant rounded hover:bg-surface-container-low z-10 shadow-sm"
          onClick={() => setSidebarOpen(true)}
        >
          Notes
        </button>
      )}

      <ReaderChatSidebar
        paperId={paperId}
        libraryId={libraryId}
        absolutePath={String(document.absolute_path || '')}
        isOpen={chatOpen}
        onToggle={() => setChatOpen(!chatOpen)}
      />
    </div>
  );
}
