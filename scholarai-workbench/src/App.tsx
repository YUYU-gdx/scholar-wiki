import { useState, useEffect, createContext, useContext } from 'react';
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
} from 'lucide-react';
import { AnimatePresence } from './components/AnimatePresence';
import LibraryView from './components/LibraryView';
import ChatView from './components/ChatView';
import GraphView from './components/GraphView';
import ReaderView from './components/ReaderView';
import PipelineView from './components/PipelineView';
import { api } from './api';
import type { View, GraphFull, ChatSession, LiteratureLibrary, PipelineJob } from './types';

type AppContextType = {
  currentView: View;
  setCurrentView: (v: View) => void;
  graphData: GraphFull | null;
  setGraphData: React.Dispatch<React.SetStateAction<GraphFull | null>>;
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  selectedPaperId: string | null;
  setSelectedPaperId: (id: string | null) => void;
  sessions: ChatSession[];
  setSessions: React.Dispatch<React.SetStateAction<ChatSession[]>>;
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  libraries: LiteratureLibrary[];
  activeLibraryId: string;
  setActiveLibraryId: (id: string) => void;
  pipelineJobs: PipelineJob[];
  setPipelineJobs: React.Dispatch<React.SetStateAction<PipelineJob[]>>;
  graphLoading: boolean;
};

export const AppContext = createContext<AppContextType>(null!);

export function useApp() {
  return useContext(AppContext);
}

export default function App() {
  const [currentView, setCurrentView] = useState<View>('graph');
  const [graphData, setGraphData] = useState<GraphFull | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [libraries, setLibraries] = useState<LiteratureLibrary[]>([]);
  const [activeLibraryId, setActiveLibraryId] = useState('supply_chain');
  const [pipelineJobs, setPipelineJobs] = useState<PipelineJob[]>([]);

  useEffect(() => {
    api.literature.listLibraries().then((res) => {
      setLibraries(res.libraries);
      if (res.default_library_id) setActiveLibraryId(res.default_library_id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!activeLibraryId) return;
    api.chat.listSessions(activeLibraryId).then((res) => {
      setSessions(res.sessions || []);
    }).catch(() => {});
  }, [activeLibraryId]);

  useEffect(() => {
    setGraphLoading(true);
    api.graph.full(activeLibraryId).then((data) => {
      setGraphData(data);
      setGraphLoading(false);
    }).catch(() => {
      setGraphLoading(false);
    });
  }, [activeLibraryId]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const libraryId = detail?.libraryId || activeLibraryId;
      setGraphLoading(true);
      api.graph.full(libraryId).then((data) => {
        setGraphData(data);
        setGraphLoading(false);
      }).catch(() => {
        setGraphLoading(false);
      });
    };
    window.addEventListener('pipeline-completed', handler as EventListener);
    return () => window.removeEventListener('pipeline-completed', handler as EventListener);
  }, [activeLibraryId]);

  const navItems = [
    { id: 'library' as View, icon: Library, label: 'Library' },
    { id: 'graph' as View, icon: Share2, label: 'Graph' },
    { id: 'chat' as View, icon: MessageSquare, label: 'Chat' },
    { id: 'reader' as View, icon: BookOpen, label: 'Reader' },
    { id: 'pipeline' as View, icon: Database, label: 'Pipeline' },
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
    setSelectedNodeId,
    selectedPaperId,
    setSelectedPaperId,
    sessions,
    setSessions,
    activeSessionId,
    setActiveSessionId,
    libraries,
    activeLibraryId,
    setActiveLibraryId,
    pipelineJobs,
    setPipelineJobs,
    graphLoading,
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
            <label className="text-[10px] font-mono text-outline uppercase tracking-widest block mb-1">Library</label>
            <select
              value={activeLibraryId}
              onChange={(e) => setActiveLibraryId(e.target.value)}
              className="w-full bg-surface-container border border-outline-variant rounded-lg px-2 py-1.5 text-xs text-on-surface outline-none focus:ring-1 focus:ring-secondary/30"
            >
              {libraries.map((lib) => (
                <option key={lib.library_id} value={lib.library_id}>{lib.library_id} ({lib.paper_count})</option>
              ))}
            </select>
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

          <div className="mt-4 flex flex-col gap-1 border-t border-outline-variant pt-4">
            <button className="flex items-center gap-3 px-3 py-2 text-on-surface-variant hover:bg-surface-container rounded-lg text-[13px] font-medium transition-colors">
              <Settings className="w-5 h-5" />
              <span>Settings</span>
            </button>
          </div>
        </aside>

        <main className="flex-1 flex flex-col relative overflow-hidden bg-background">
          <header className="h-12 border-b border-outline-variant bg-surface-container-lowest/80 backdrop-blur-md flex justify-between items-center px-6 z-40">
            <div className="flex items-center flex-1 max-w-md">
              <div className="relative w-full group">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-outline group-focus-within:text-secondary transition-colors" />
                <input
                  type="text"
                  placeholder="Search variables, papers..."
                  className="w-full bg-surface-container border border-outline-variant rounded-lg px-10 py-1.5 text-sm font-mono focus:ring-1 focus:ring-secondary/30 outline-none transition-all placeholder:text-outline"
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
            <div className="flex items-center gap-4">
              <button className="text-on-surface-variant hover:text-secondary transition-all flex items-center gap-1.5 focus:outline-none">
                <Zap className="w-4 h-4" />
                <span className="text-[11px] font-mono uppercase tracking-wider">Live</span>
              </button>
              <button className="text-on-surface-variant hover:text-secondary transition-all relative focus:outline-none">
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
              </div>
            </AnimatePresence>
          </div>
        </main>
      </div>
    </AppContext.Provider>
  );
}