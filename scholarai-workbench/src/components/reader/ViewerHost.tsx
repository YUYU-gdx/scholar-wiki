import { useState, useEffect } from 'react';
import { FileText, AlertCircle, StickyNote, Link2, Network, MessageSquare } from 'lucide-react';
import PdfViewer from './PdfViewer';
import MarkdownEditor from './MarkdownEditor';
import AnnotationSidebar from './AnnotationSidebar';
import ReaderChatSidebar from './ReaderChatSidebar';
import BacklinksPanel from './BacklinksPanel';
import RelatedEntities from './RelatedEntities';
import { useApp } from '../../app-context';
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
  const [backlinksOpen, setBacklinksOpen] = useState(false);
  const [entitiesOpen, setEntitiesOpen] = useState(false);
  const app = useApp();
  const graphData = app?.graphData ?? null;
  const primaryPaperId = String(rawPaperId || paperId || '').trim();

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
          <p className="text-sm text-on-surface-variant">加载文档中...</p>
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
          <p className="text-sm text-on-surface-variant">该论文无可读文件。</p>
          <p className="text-xs text-outline">{paperId}</p>
        </div>
      </div>
    );
  }

  const effectiveMarkdownPath = String(
    document.type === 'markdown'
      ? (document.absolute_path || '')
      : (document.markdown_path || ''),
  ).trim();

  return (
    <div className="flex-1 flex overflow-hidden relative">
      <div className="flex-1 flex flex-col overflow-hidden md:pr-24">
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
              HTML 闃呰鍣ㄥ凡涓存椂灏佸瓨銆傝浼樺厛浣跨敤 PDF 鎴?Markdown銆?
            </div>
          </div>
        )}
      </div>

      {(document.type === 'pdf' || document.type === 'markdown') && (
        <AnnotationSidebar
          paperId={primaryPaperId}
          libraryId={libraryId}
          markdownPath={effectiveMarkdownPath}
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
        />
      )}

      {(document.type === 'pdf' || document.type === 'markdown') && (
        <BacklinksPanel
          paperId={primaryPaperId}
          libraryId={libraryId}
          currentMarkdownPath={effectiveMarkdownPath}
          isOpen={backlinksOpen}
          onToggle={() => setBacklinksOpen(!backlinksOpen)}
        />
      )}

      {(document.type === 'pdf' || document.type === 'markdown') && (
        <RelatedEntities
          paperId={primaryPaperId}
          libraryId={libraryId}
          graphData={graphData}
          isOpen={entitiesOpen}
          onToggle={() => setEntitiesOpen(!entitiesOpen)}
        />
      )}

      {(document.type === 'pdf' || document.type === 'markdown') && (
        <div className="absolute right-3 top-16 z-20 hidden md:flex flex-col gap-2">
          <button
            className={`inline-flex items-center justify-center gap-2 w-11 h-11 rounded-xl border text-xs font-semibold shadow-sm transition-all group hover:w-[118px] hover:justify-start hover:px-3 ${
              sidebarOpen
                ? 'bg-secondary-container/20 border-secondary/40 text-secondary'
                : 'bg-surface-container-lowest/90 backdrop-blur border-outline-variant text-on-surface-variant hover:text-on-surface hover:border-secondary/40 hover:bg-surface-container-low'
            }`}
            onClick={() => setSidebarOpen((v) => !v)}
            title="笔记"
          >
            <StickyNote className="w-3.5 h-3.5" />
            <span className="hidden group-hover:inline">笔记</span>
          </button>
          <button
            className={`inline-flex items-center justify-center gap-2 w-11 h-11 rounded-xl border text-xs font-semibold shadow-sm transition-all group hover:w-[118px] hover:justify-start hover:px-3 ${
              backlinksOpen
                ? 'bg-secondary-container/20 border-secondary/40 text-secondary'
                : 'bg-surface-container-lowest/90 backdrop-blur border-outline-variant text-on-surface-variant hover:text-on-surface hover:border-secondary/40 hover:bg-surface-container-low'
            }`}
            onClick={() => setBacklinksOpen((v) => !v)}
            title="链接"
          >
            <Link2 className="w-3.5 h-3.5" />
            <span className="hidden group-hover:inline">链接</span>
          </button>
          <button
            className={`inline-flex items-center justify-center gap-2 w-11 h-11 rounded-xl border text-xs font-semibold shadow-sm transition-all group hover:w-[118px] hover:justify-start hover:px-3 ${
              entitiesOpen
                ? 'bg-secondary-container/20 border-secondary/40 text-secondary'
                : 'bg-surface-container-lowest/90 backdrop-blur border-outline-variant text-on-surface-variant hover:text-on-surface hover:border-secondary/40 hover:bg-surface-container-low'
            }`}
            onClick={() => setEntitiesOpen((v) => !v)}
            title="实体"
          >
            <Network className="w-3.5 h-3.5" />
            <span className="hidden group-hover:inline">实体</span>
          </button>
          <button
            className={`inline-flex items-center justify-center gap-2 w-11 h-11 rounded-xl border text-xs font-semibold shadow-sm transition-all group hover:w-[118px] hover:justify-start hover:px-3 ${
              chatOpen
                ? 'bg-secondary-container/20 border-secondary/40 text-secondary'
                : 'bg-surface-container-lowest/90 backdrop-blur border-outline-variant text-on-surface-variant hover:text-on-surface hover:border-secondary/40 hover:bg-surface-container-low'
            }`}
            onClick={() => setChatOpen((v) => !v)}
            title="阅读器对话"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span className="hidden group-hover:inline">阅读器对话</span>
          </button>
        </div>
      )}

      {(document.type === 'pdf' || document.type === 'markdown') && (
        <div className="absolute left-1/2 bottom-3 -translate-x-1/2 z-20 md:hidden flex items-center gap-1.5 rounded-2xl border border-outline-variant bg-surface-container-lowest/95 backdrop-blur px-2 py-1.5 shadow-lg">
          <button
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[13px] ${
              sidebarOpen ? 'bg-secondary-container/20 border-secondary/40 text-secondary' : 'border-outline-variant text-on-surface-variant'
            }`}
            onClick={() => setSidebarOpen((v) => !v)}
          >
            <StickyNote className="w-3.5 h-3.5" /> 笔记
          </button>
          <button
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[13px] ${
              backlinksOpen ? 'bg-secondary-container/20 border-secondary/40 text-secondary' : 'border-outline-variant text-on-surface-variant'
            }`}
            onClick={() => setBacklinksOpen((v) => !v)}
          >
            <Link2 className="w-3.5 h-3.5" /> 链接
          </button>
          <button
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[13px] ${
              entitiesOpen ? 'bg-secondary-container/20 border-secondary/40 text-secondary' : 'border-outline-variant text-on-surface-variant'
            }`}
            onClick={() => setEntitiesOpen((v) => !v)}
          >
            <Network className="w-3.5 h-3.5" /> 实体
          </button>
          <button
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[13px] ${
              chatOpen ? 'bg-secondary-container/20 border-secondary/40 text-secondary' : 'border-outline-variant text-on-surface-variant'
            }`}
            onClick={() => setChatOpen((v) => !v)}
          >
            <MessageSquare className="w-3.5 h-3.5" /> 对话
          </button>
        </div>
      )}

      <ReaderChatSidebar
        paperId={primaryPaperId}
        libraryId={libraryId}
        absolutePath={String(document.absolute_path || '')}
        isOpen={chatOpen}
        onToggle={() => setChatOpen(!chatOpen)}
        showClosedToggle={false}
      />
    </div>
  );
}

