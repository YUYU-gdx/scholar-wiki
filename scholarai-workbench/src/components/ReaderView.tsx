import { BookOpen, FileText, ArrowLeft } from 'lucide-react';
import { useApp } from '../App';
import ViewerHost from './reader/ViewerHost';

export default function ReaderView() {
  const {
    selectedPaperId,
    selectedPaperLibraryId,
    setSelectedPaperId,
    selectedNodeId,
    setCurrentView,
  } = useApp();

  if (!selectedPaperId && !selectedNodeId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-4">
          <BookOpen className="w-12 h-12 text-outline mx-auto" />
          <h3 className="text-lg font-medium text-on-surface">Document Reader</h3>
          <p className="text-sm text-on-surface-variant max-w-md">
            Select a paper from the Graph or Library view to read its full text.
            Supports PDF and Markdown documents.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <button
          className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          onClick={() => {
            setSelectedPaperId(null);
            setCurrentView('graph');
          }}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="flex items-center gap-2 ml-2">
          <FileText className="w-4 h-4 text-secondary" />
          <span className="text-xs font-mono text-on-surface truncate max-w-[400px]">
            {selectedPaperId || selectedNodeId || 'Document'}
          </span>
        </div>
      </div>

      {selectedPaperId ? (
        <ViewerHost paperId={selectedPaperId} libraryId={selectedPaperLibraryId} />
      ) : selectedNodeId ? (
        <div className="flex-1 flex items-center justify-center bg-surface-container-low">
          <div className="text-center space-y-3">
            <BookOpen className="w-8 h-8 text-outline mx-auto" />
            <p className="text-sm text-on-surface-variant">
              Variable detail view — select a paper to open documents.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
