import { useState, useEffect, createContext, useContext, useMemo } from 'react';
import {
  Library,
  Share2,
  MessageSquare,
  BookOpen,
  Database,
  Settings,
  Search,
  Zap,
  Bell,
  Trash2,
  Plus,
} from 'lucide-react';
import { AnimatePresence } from './components/AnimatePresence';
import LibraryView from './components/LibraryView';
import ChatView from './components/ChatView';
import GraphView from './components/GraphView';
import ReaderView from './components/ReaderView';
import PipelineView from './components/PipelineView';
import SettingsView from './components/SettingsView';
import { api } from './api';
import type { View, GraphFull, ChatSession, LiteratureLibrary, PipelineJob, GraphNode, GraphEdge } from './types';

type AppContextType = {
  currentView: View;
  setCurrentView: (v: View) => void;
  graphData: GraphFull | null;
  setGraphData: React.Dispatch<React.SetStateAction<GraphFull | null>>;
  selectedNodeId: string | null;
  selectedNodeLibraryId: string;
  setSelectedNodeId: (id: string | null) => void;
  setSelectedNodeLibraryId: (id: string) => void;
  selectedPaperId: string | null;
  selectedPaperLibraryId: string;
  setSelectedPaperId: (id: string | null) => void;
  setSelectedPaperLibraryId: (id: string) => void;
  selectedPaperPreferredType: 'pdf' | 'markdown' | 'html' | null;
  setSelectedPaperPreferredType: (type: 'pdf' | 'markdown' | 'html' | null) => void;
  selectedPaperRawId: string | null;
  setSelectedPaperRawId: (id: string | null) => void;
  readerReturnView: 'library' | 'graph';
  setReaderReturnView: (v: 'library' | 'graph') => void;
  sessions: ChatSession[];
  setSessions: React.Dispatch<React.SetStateAction<ChatSession[]>>;
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  libraries: LiteratureLibrary[];
  activeLibraryId: string;
  setActiveLibraryId: (id: string) => void;
  selectedLibraryIds: string[];
  setSelectedLibraryIds: React.Dispatch<React.SetStateAction<string[]>>;
  pipelineJobs: PipelineJob[];
  setPipelineJobs: React.Dispatch<React.SetStateAction<PipelineJob[]>>;
  graphLoading: boolean;
  paperFileCache: Record<string, { pdf: boolean; markdown: boolean; html: boolean; loaded: boolean }>;
  setPaperFileCache: React.Dispatch<React.SetStateAction<Record<string, { pdf: boolean; markdown: boolean; html: boolean; loaded: boolean }>>>;
};

export const AppContext = createContext<AppContextType>(null!);

export function useApp() {
  return useContext(AppContext);
}

function mergeGraphPayloads(payloads: GraphFull[]): GraphFull {
  const nodeById = new Map<string, GraphNode>();
  const edgeByKey = new Map<string, GraphEdge>();
  const paperMap: Record<string, unknown> = {};
  const isolatedById = new Map<string, { node_id: string; label?: string; reason?: string }>();

  for (const p of payloads) {
    const libId = String(p.meta?.library_id || p.meta?.dataset_scope || '');
    for (const n of p.nodes || []) {
      const node = { ...n, library_id: libId };
      const ex = nodeById.get(node.id);
      if (!ex) {
        nodeById.set(node.id, node);
      } else {
        nodeById.set(node.id, {
          ...ex,
          ...node,
          relation_degree: Math.max(Number(ex.relation_degree || 0), Number(n.relation_degree || 0)),
          paper_count: Math.max(Number(ex.paper_count || 0), Number(n.paper_count || 0)),
        });
      }
    }
    for (const e of p.edges || []) {
      const src = typeof e.source === 'object' ? e.source?.id : e.source;
      const tgt = typeof e.target === 'object' ? e.target?.id : e.target;
      const key = `${src}=>${tgt}::${e.paper_id || ''}::${e.direction || ''}`;
      if (!edgeByKey.has(key)) edgeByKey.set(key, e);
    }
    for (const [paperId, paperVal] of Object.entries(p.paper_map || {})) {
      const scoped = `${libId}::${paperId}`;
      paperMap[scoped] = { ...(paperVal as Record<string, unknown>), paper_id: paperId, library_id: libId };
    }
    for (const iso of p.isolated_nodes || []) {
      isolatedById.set(iso.node_id, iso);
    }
  }

  return {
    meta: {
      paper_count: Object.keys(paperMap).length,
      node_count: nodeById.size,
      edge_count: edgeByKey.size,
      library_count: payloads.length,
      library_id: payloads[0]?.meta?.library_id,
    },
    nodes: [...nodeById.values()],
    edges: [...edgeByKey.values()],
    moderation_links: payloads.flatMap((p) => p.moderation_links || []),
    interaction_links: payloads.flatMap((p) => p.interaction_links || []),
    isolated_nodes: [...isolatedById.values()],
    paper_map: paperMap as GraphFull['paper_map'],
  };
}

export default function App() {
  const [currentView, setCurrentView] = useState<View>('library');
  const [graphData, setGraphData] = useState<GraphFull | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeLibraryId, setSelectedNodeLibraryId] = useState<string>('');
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  const [selectedPaperLibraryId, setSelectedPaperLibraryId] = useState<string>('');
  const [selectedPaperPreferredType, setSelectedPaperPreferredType] = useState<'pdf' | 'markdown' | 'html' | null>(null);
  const [selectedPaperRawId, setSelectedPaperRawId] = useState<string | null>(null);
  const [readerReturnView, setReaderReturnView] = useState<'library' | 'graph'>('library');
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [libraries, setLibraries] = useState<LiteratureLibrary[]>([]);
  const [activeLibraryId, setActiveLibraryId] = useState('');
  const [selectedLibraryIds, setSelectedLibraryIds] = useState<string[]>(['']);
  const [pipelineJobs, setPipelineJobs] = useState<PipelineJob[]>([]);
  const [paperFileCache, setPaperFileCache] = useState<Record<string, { pdf: boolean; markdown: boolean; html: boolean; loaded: boolean }>>({});
  const [creatingLibrary, setCreatingLibrary] = useState(false);
  const [newLibraryId, setNewLibraryId] = useState('');

  const refreshLibraries = () => {
    api.literature.listLibraries().then((res) => {
      setLibraries(res.libraries);
      const fallback = res.default_library_id || res.libraries[0]?.library_id || '';
      setActiveLibraryId(fallback);
      setSelectedLibraryIds([fallback]);
      setSelectedNodeLibraryId(fallback);
      setSelectedPaperLibraryId(fallback);
    }).catch(() => {});
  };

  useEffect(() => {
    refreshLibraries();
    const onDelete = (e: Event) => {
      const libId = (e as CustomEvent).detail?.libraryId || '';
      if (libId) api.graph.full(libId).then((p) => setGraphData((prev) => mergeGraphPayloads([p, prev]))).catch(() => {});
    };
    window.addEventListener('paper-deleted', onDelete);
    return () => window.removeEventListener('paper-deleted', onDelete);
  }, []);

  useEffect(() => {
    if (!activeLibraryId) return;
    api.chat.listSessions(activeLibraryId).then((res) => {
      setSessions(res.sessions || []);
    }).catch(() => {});
  }, [activeLibraryId]);

  const selectedKey = useMemo(() => selectedLibraryIds.slice().sort().join('|'), [selectedLibraryIds]);

  useEffect(() => {
    const libIds = selectedLibraryIds.length ? selectedLibraryIds : (activeLibraryId ? [activeLibraryId] : []);
    if (!libIds.length) return;
    setGraphLoading(true);
    Promise.all(libIds.map((libId) => api.graph.full(libId))).then((payloads) => {
      setGraphData(mergeGraphPayloads(payloads));
      setGraphLoading(false);
    }).catch(() => {
      setGraphLoading(false);
    });
  }, [selectedKey, activeLibraryId]);

  useEffect(() => {
    const handler = () => {
      const libIds = selectedLibraryIds.length ? selectedLibraryIds : (activeLibraryId ? [activeLibraryId] : []);
      if (!libIds.length) return;
      setGraphLoading(true);
      Promise.all(libIds.map((libId) => api.graph.full(libId))).then((payloads) => {
        setGraphData(mergeGraphPayloads(payloads));
        setGraphLoading(false);
      }).catch(() => {
        setGraphLoading(false);
      });
    };
    window.addEventListener('pipeline-completed', handler as EventListener);
    return () => window.removeEventListener('pipeline-completed', handler as EventListener);
  }, [selectedKey, activeLibraryId]);

  const navItems = [
    { id: 'library' as View, icon: Library, label: 'Library' },
    { id: 'graph' as View, icon: Share2, label: 'Graph' },
    { id: 'chat' as View, icon: MessageSquare, label: 'Chat' },
    { id: 'reader' as View, icon: BookOpen, label: 'Reader' },
    { id: 'pipeline' as View, icon: Database, label: 'Pipeline' },
    { id: 'settings' as View, icon: Settings, label: 'Settings' },
  ];

  const nodeCount = graphData?.nodes?.filter(n => String(n.type || '') === 'variable' && !!n.validated_variable && Number(n.relation_degree || 0) > 0).length ?? 0;
  const edgeCount = graphData?.edges?.length ?? 0;
  const paperCount = graphData?.meta?.paper_count ?? 0;

  const ctx: AppContextType = {
    currentView,
    setCurrentView,
    graphData,
    setGraphData,
    selectedNodeId,
    selectedNodeLibraryId,
    setSelectedNodeId,
    setSelectedNodeLibraryId,
    selectedPaperId,
    selectedPaperLibraryId,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    selectedPaperPreferredType,
    setSelectedPaperPreferredType,
    selectedPaperRawId,
    setSelectedPaperRawId,
    readerReturnView,
    setReaderReturnView,
    sessions,
    setSessions,
    activeSessionId,
    setActiveSessionId,
    libraries,
    activeLibraryId,
    setActiveLibraryId,
    selectedLibraryIds,
    setSelectedLibraryIds,
    pipelineJobs,
    setPipelineJobs,
    graphLoading,
    paperFileCache,
    setPaperFileCache,
  };

  return (
    <AppContext.Provider value={ctx}>
      <div className="flex h-screen bg-surface-container-low text-on-surface overflow-hidden font-sans">
        <aside className="w-64 border-r border-outline-variant bg-surface-container-lowest glass-shadow z-50 flex flex-col py-6 px-4 gap-2">
          <div className="mb-8 px-2 flex items-center gap-3">
            <div className="w-8 h-8 bg-primary-container text-on-primary-container rounded flex items-center justify-center">
              <Share2 className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tighter text-on-surface leading-none">ScholarAI</h1>
              <p className="text-[10px] font-mono uppercase tracking-widest text-on-surface-variant mt-1">KN Graph Workbench</p>
            </div>
          </div>

          <div className="px-2 mb-2">
            <div className="flex items-center justify-between mb-1">
              <label className="text-[10px] font-mono text-outline uppercase tracking-widest">Libraries (Multi-select)</label>
              <button
                type="button"
                title="创建文献库"
                className="p-1 rounded border border-outline-variant text-outline hover:text-secondary hover:border-secondary"
                onClick={() => {
                  setCreatingLibrary((v) => !v);
                  if (!creatingLibrary) setNewLibraryId('new_library');
                }}
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>
            {creatingLibrary && (
              <div className="mb-2 flex items-center gap-1.5" key="create-lib">
                <input
                  autoFocus
                  defaultValue={newLibraryId}
                  onInput={(e) => setNewLibraryId((e.target as HTMLInputElement).value)}
                  placeholder="library_id"
                  className="flex-1 bg-surface-container border border-outline-variant rounded px-2 py-1 text-xs font-mono text-on-surface outline-none focus:border-secondary"
                />
                <button
                  type="button"
                  className="px-2 py-1 text-[11px] rounded border border-outline-variant hover:border-secondary"
                  onClick={async () => {
                    const libraryId = newLibraryId.trim();
                    if (!libraryId) return;
                    try {
                      await api.literature.createLibrary(libraryId, '', false);
                      setCreatingLibrary(false);
                      setNewLibraryId('');
                      refreshLibraries();
                    } catch (err) {
                      window.alert(`创建失败: ${String((err as Error)?.message || err)}`);
                    }
                  }}
                >
                  创建
                </button>
                <button
                  type="button"
                  className="px-2 py-1 text-[11px] rounded border border-outline-variant hover:border-secondary"
                  onClick={() => {
                    setCreatingLibrary(false);
                    setNewLibraryId('');
                  }}
                >
                  取消
                </button>
              </div>
            )}
            <div className="max-h-36 overflow-auto rounded-lg border border-outline-variant bg-surface-container p-1.5 space-y-1">
              {libraries.map((lib) => {
                const checked = selectedLibraryIds.includes(lib.library_id);
                return (
                  <div key={lib.library_id} className="flex items-center justify-between gap-2 px-1.5 py-1 rounded hover:bg-surface-container-low">
                    <label className="flex items-center gap-2 cursor-pointer flex-1 min-w-0">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...selectedLibraryIds, lib.library_id]
                            : selectedLibraryIds.filter((id) => id !== lib.library_id);
                          const ensured = next.length ? next : [lib.library_id];
                          setSelectedLibraryIds(ensured);
                          setActiveLibraryId(ensured[0]);
                        }}
                      />
                      <span className="text-xs text-on-surface truncate">{lib.library_id}</span>
                    </label>
                    <button
                      type="button"
                      title={`删除库 ${lib.library_id}`}
                      className="p-1 rounded border border-outline-variant text-outline hover:text-red-500 hover:border-red-400"
                      onClick={async () => {
                        const ok = window.confirm(`确认删除库 ${lib.library_id}？这会删除该库的索引与工作区数据。`);
                        if (!ok) return;
                        try {
                          await api.literature.deleteLibrary(lib.library_id, true);
                          refreshLibraries();
                        } catch (err) {
                          // eslint-disable-next-line no-alert
                          window.alert(`删除失败: ${String((err as Error)?.message || err)}`);
                        }
                      }}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          <nav className="flex-1 flex flex-col gap-1">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setCurrentView(item.id)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-[13px] font-medium tracking-tight ${
                  currentView === item.id
                  ? 'text-secondary border-r-2 border-secondary bg-secondary-container/30'
                  : 'text-on-surface-variant hover:bg-surface-container'
                }`}
              >
                <item.icon className="w-5 h-5" />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          <div className="mt-auto space-y-3 px-2">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-2 bg-surface-container rounded-lg">
                <p className="text-sm font-bold text-on-surface">{nodeCount}</p>
                <p className="text-[9px] text-outline font-mono uppercase">Nodes</p>
              </div>
              <div className="p-2 bg-surface-container rounded-lg">
                <p className="text-sm font-bold text-on-surface">{edgeCount}</p>
                <p className="text-[9px] text-outline font-mono uppercase">Edges</p>
              </div>
              <div className="p-2 bg-surface-container rounded-lg">
                <p className="text-sm font-bold text-on-surface">{paperCount}</p>
                <p className="text-[9px] text-outline font-mono uppercase">Papers</p>
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-col gap-1 border-t border-outline-variant pt-4" />
        </aside>

        <main className="flex-1 flex flex-col relative overflow-hidden bg-background">
          <header className="electron-drag h-12 border-b border-outline-variant bg-surface-container-lowest/80 backdrop-blur-md flex justify-between items-center px-6 z-40">
            <div className="electron-no-drag flex items-center flex-1 max-w-md">
              <div className="relative w-full group">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-outline group-focus-within:text-secondary transition-colors" />
                <input
                  type="text"
                  placeholder="Search variables, papers..."
                  className="electron-no-drag w-full bg-surface-container border border-outline-variant rounded-lg px-10 py-1.5 text-sm font-mono focus:ring-1 focus:ring-secondary/30 outline-none transition-all placeholder:text-outline"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                      setSelectedNodeId(null);
                      setSelectedPaperId(null);
                      setCurrentView('graph');
                    }
                  }}
                />
              </div>
            </div>
            <div className="electron-no-drag flex items-center gap-4">
              <button className="electron-no-drag text-on-surface-variant hover:text-secondary transition-all flex items-center gap-1.5 focus:outline-none">
                <Zap className="w-4 h-4" />
                <span className="text-[11px] font-mono uppercase tracking-wider">Live</span>
              </button>
              <button className="electron-no-drag text-on-surface-variant hover:text-secondary transition-all relative focus:outline-none">
                <Bell className="w-4 h-4" />
              </button>
            </div>
          </header>

          <div className="flex-1 relative overflow-hidden">
            <AnimatePresence mode="wait">
              <div
                key={currentView}
                className="absolute inset-0 flex animate-fade-in"
              >
                {currentView === 'library' && <LibraryView />}
                {currentView === 'graph' && <GraphView />}
                {currentView === 'chat' && <ChatView />}
                {currentView === 'reader' && <ReaderView />}
                {currentView === 'pipeline' && <PipelineView />}
                {currentView === 'settings' && <SettingsView />}
              </div>
            </AnimatePresence>
          </div>
        </main>
      </div>
    </AppContext.Provider>
  );
}
