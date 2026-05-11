import { BookOpen, FileText, ArrowLeft } from 'lucide-react';
import { useState, useCallback, useEffect } from 'react';
import { useApp } from '../App';
import ViewerHost from './reader/ViewerHost';
import TabBar from './reader/TabBar';
import type { TabDescriptor } from './reader/types';

const MAX_TABS = 8;
const READER_TABS_KEY = 'kn_graph_reader_tabs_v1';
const READER_ACTIVE_TAB_KEY = 'kn_graph_reader_active_tab_v1';

export default function ReaderView() {
  const [docPath, setDocPath] = useState('');
  const [tabs, setTabs] = useState<TabDescriptor[]>(() => {
    try {
      const raw = sessionStorage.getItem(READER_TABS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((t) => t && typeof t === 'object')
        .map((t) => ({
          id: String(t.id || crypto.randomUUID()),
          paperId: String(t.paperId || ''),
          libraryId: String(t.libraryId || ''),
          type: (t.type === 'pdf' || t.type === 'markdown' || t.type === 'html') ? t.type : 'markdown',
          path: String(t.path || ''),
          title: String(t.title || t.paperId || 'Document'),
        }))
        .filter((t) => t.paperId && t.libraryId);
    } catch {
      return [];
    }
  });
  const [activeTabId, setActiveTabId] = useState<string | null>(() => {
    try {
      const v = sessionStorage.getItem(READER_ACTIVE_TAB_KEY);
      return v || null;
    } catch {
      return null;
    }
  });
  const {
    selectedPaperId,
    selectedPaperLibraryId,
    setSelectedPaperId,
    setSelectedNodeId,
    setSelectedPaperRawId,
    setSelectedPaperPreferredType,
    selectedNodeId,
    selectedPaperPreferredType,
    selectedPaperRawId,
    readerReturnView,
    setCurrentView,
  } = useApp();

  useEffect(() => {
    try {
      sessionStorage.setItem(READER_TABS_KEY, JSON.stringify(tabs));
    } catch {
      // ignore persistence errors
    }
  }, [tabs]);

  useEffect(() => {
    try {
      if (activeTabId) sessionStorage.setItem(READER_ACTIVE_TAB_KEY, activeTabId);
      else sessionStorage.removeItem(READER_ACTIVE_TAB_KEY);
    } catch {
      // ignore persistence errors
    }
  }, [activeTabId]);

  useEffect(() => {
    if (!tabs.length) {
      if (activeTabId) setActiveTabId(null);
      return;
    }
    if (!activeTabId || !tabs.some((t) => t.id === activeTabId)) {
      setActiveTabId(tabs[tabs.length - 1].id);
    }
  }, [tabs, activeTabId]);

  useEffect(() => {
    if (!selectedPaperId) return;
    const targetPaperId = String(selectedPaperId || '').trim();
    const targetLibraryId = String(selectedPaperLibraryId || '').trim();
    if (!targetPaperId || !targetLibraryId) {
      setSelectedPaperId(null);
      return;
    }
    setTabs((prev) => {
      const existing = prev.find((t) => t.paperId === targetPaperId && t.libraryId === targetLibraryId);
      if (existing) {
        setActiveTabId(existing.id);
        return prev;
      }
      const newTab: TabDescriptor = {
        id: crypto.randomUUID(),
        paperId: targetPaperId,
        libraryId: targetLibraryId,
        type: (selectedPaperPreferredType as TabDescriptor['type']) || 'markdown',
        path: '',
        title: targetPaperId,
      };
      const next = [...prev, newTab];
      setActiveTabId(newTab.id);
      return next.length > MAX_TABS ? next.slice(next.length - MAX_TABS) : next;
    });
    setSelectedPaperId(null);
  }, [selectedPaperId, selectedPaperLibraryId, selectedPaperPreferredType, setSelectedPaperId]);

  const closeTab = useCallback((tabId: string) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.id === tabId);
      const next = prev.filter(t => t.id !== tabId);
      if (activeTabId === tabId && next.length > 0) {
        const newIdx = Math.min(idx, next.length - 1);
        setActiveTabId(next[newIdx].id);
      } else if (next.length === 0) {
        setActiveTabId(null);
      }
      return next;
    });
  }, [activeTabId]);

  const activeTab = tabs.find(t => t.id === activeTabId) || null;

  const handleDocumentMeta = useCallback((meta: { absolutePath: string; fileName: string; type: 'pdf' | 'markdown' | 'html' | 'none' }) => {
    setDocPath(meta.absolutePath || '');
    if (activeTabId) {
      setTabs(prev => {
        const active = prev.find((t) => t.id === activeTabId);
        if (!active) return prev;
        const normalizedPath = String(meta.absolutePath || '').trim().toLowerCase();
        const duplicate = normalizedPath
          ? prev.find((t) => t.id !== activeTabId && String(t.path || '').trim().toLowerCase() === normalizedPath)
          : null;
        if (duplicate) {
          setActiveTabId(duplicate.id);
          return prev.filter((t) => t.id !== activeTabId);
        }
        return prev.map(t =>
          t.id === activeTabId
            ? {
                ...t,
                path: meta.absolutePath || t.path,
                title: meta.fileName || t.title,
                type: meta.type === 'none' ? t.type : meta.type,
              }
            : t
        );
      });
    }
  }, [activeTabId]);

  if (!activeTab && !selectedPaperId && !selectedNodeId) {
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

  const displayPath = activeTab?.path || docPath;
  const displayTitle = activeTab?.title || selectedPaperId || selectedNodeId || 'Document';

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <TabBar
        tabs={tabs}
        activeTabId={activeTabId}
        onSelectTab={(tabId) => setActiveTabId(tabId)}
        onCloseTab={closeTab}
      />
      <div className="flex items-center gap-3 px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <button
          className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          onClick={() => {
            setTabs([]);
            setActiveTabId(null);
            setSelectedPaperId(null);
            setSelectedPaperRawId(null);
            setSelectedPaperPreferredType(null);
            setSelectedNodeId(null);
            setCurrentView(readerReturnView);
          }}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="flex items-center gap-2 ml-2">
          <FileText className="w-4 h-4 text-secondary" />
          <span className="text-xs font-mono text-on-surface truncate max-w-[400px]">
            {displayTitle}
          </span>
        </div>
        {displayPath && (
          <span className="text-[10px] text-outline truncate ml-auto max-w-[48%]" title={displayPath}>
            {displayPath}
          </span>
        )}
      </div>

      {activeTab ? (
        <ViewerHost
          key={activeTab.id}
          paperId={activeTab.paperId}
          libraryId={activeTab.libraryId}
          preferredType={activeTab.type}
          rawPaperId={selectedPaperRawId || undefined}
          onDocumentMeta={handleDocumentMeta}
        />
      ) : selectedPaperId ? (
        <ViewerHost
          key="direct"
          paperId={selectedPaperId}
          libraryId={selectedPaperLibraryId}
          preferredType={selectedPaperPreferredType}
          rawPaperId={selectedPaperRawId || undefined}
          onDocumentMeta={handleDocumentMeta}
        />
      ) : selectedNodeId ? (
        <div className="flex-1 flex items-center justify-center bg-surface-container-low">
          <div className="text-center space-y-3">
            <BookOpen className="w-8 h-8 text-outline mx-auto" />
            <p className="text-sm text-on-surface-variant">
              Variable detail view - select a paper to open documents.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
