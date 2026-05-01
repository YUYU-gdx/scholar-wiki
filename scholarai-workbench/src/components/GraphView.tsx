import { useMemo, useState } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import { MessageCircle, Search } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { GraphNode, SearchResponse } from '../types';

function nodeLabel(n: GraphNode): string {
  return n.label || n.name || n.id || 'node';
}

type GNode = { id: string; name: string; library_id?: string; fx?: number; fy?: number; fz?: number; raw: GraphNode };
type GLink = { source: string; target: string; paper_id?: string };

export default function GraphView() {
  const { graphData, selectedNodeId, setSelectedNodeId, setSelectedNodeLibraryId, setCurrentView, graphLoading, activeLibraryId } = useApp();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(null);
  const [showSearch, setShowSearch] = useState(false);

  const nodes = useMemo<GNode[]>(() => {
    if (!graphData) return [];
    return graphData.nodes
      .filter((n) => String(n.type || '') === 'variable')
      .slice(0, 240)
      .map((n) => ({
        id: n.id,
        name: nodeLabel(n),
        library_id: n.library_id,
        fx: typeof n.x === 'number' ? n.x : undefined,
        fy: typeof n.y === 'number' ? n.y : undefined,
        fz: typeof n.z === 'number' ? n.z : undefined,
        raw: n,
      }));
  }, [graphData]);

  const nodeIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);

  const links = useMemo<GLink[]>(() => {
    if (!graphData) return [];
    return graphData.edges
      .map((e) => {
        const s = typeof e.source === 'object' ? e.source?.id : e.source;
        const t = typeof e.target === 'object' ? e.target?.id : e.target;
        return { source: String(s || ''), target: String(t || ''), paper_id: e.paper_id };
      })
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .slice(0, 1200);
  }, [graphData, nodeIds]);

  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) || null, [nodes, selectedNodeId]);
  const relatedPapers = useMemo(() => {
    if (!selectedNodeId) return [];
    const ids = new Set<string>();
    for (const l of links) if (l.source === selectedNodeId || l.target === selectedNodeId) if (l.paper_id) ids.add(l.paper_id);
    return [...ids].slice(0, 12);
  }, [links, selectedNodeId]);

  const doSearch = async () => {
    if (!searchQuery.trim()) return;
    const res = await api.graph.search(searchQuery, 'variable', 12, activeLibraryId);
    setSearchResults(res);
  };

  if (graphLoading) return <div className="flex-1 flex items-center justify-center bg-[#020617] text-sm text-on-surface-variant">Loading knowledge graph...</div>;
  if (!graphData) return <div className="flex-1 flex items-center justify-center bg-[#020617] text-sm text-on-surface-variant">No graph data available.</div>;

  return (
    <div className="flex-1 relative flex overflow-hidden bg-[#020617]">
      <button onClick={() => setShowSearch(!showSearch)} className="absolute top-6 left-6 z-20 bg-surface-container-low/60 border border-outline-variant/30 rounded-xl p-2.5"><Search className="w-4 h-4 text-secondary" /></button>
      {showSearch && (
        <div className="absolute top-16 left-6 w-80 z-20 bg-surface-container-low/60 backdrop-blur-xl border border-outline-variant/30 rounded-2xl p-4">
          <div className="flex gap-2 mb-3">
            <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void doSearch(); }} placeholder="Search variables..." className="flex-1 bg-surface-container/10 border border-outline-variant/30 rounded-lg px-3 py-1.5 text-xs text-on-surface" />
            <button onClick={() => void doSearch()} className="bg-secondary/20 text-secondary px-3 py-1.5 rounded-lg text-xs">Search</button>
          </div>
          {searchResults && <div className="space-y-2 max-h-60 overflow-auto">{searchResults.results.map((r) => <button key={r.id} onClick={() => setSelectedNodeId(r.id)} className="w-full text-left p-2 border border-outline-variant/30 rounded text-xs text-on-surface-variant">{r.title || r.id}</button>)}</div>}
        </div>
      )}

      <div className="flex-1">
        <ForceGraph3D
          graphData={{ nodes, links }}
          nodeLabel={(n) => (n as GNode).name}
          nodeColor={(n) => ((n as GNode).id === selectedNodeId ? '#14b8a6' : '#cbd5e1')}
          nodeVal={(n) => ((n as GNode).id === selectedNodeId ? 7 : 4)}
          linkColor={(l) => (((l as GLink).source === selectedNodeId || (l as GLink).target === selectedNodeId) ? '#14b8a6' : '#334155')}
          linkWidth={(l) => (((l as GLink).source === selectedNodeId || (l as GLink).target === selectedNodeId) ? 2 : 0.8)}
          onNodeClick={(n) => {
            const node = n as GNode;
            setSelectedNodeId(node.id);
            setSelectedNodeLibraryId(String(node.library_id || activeLibraryId));
          }}
          backgroundColor="#020617"
        />
      </div>

      <aside className="w-[390px] bg-surface-container-lowest/10 backdrop-blur-2xl border-l border-outline-variant/30 flex flex-col overflow-hidden">
        <div className="p-5 border-b border-outline-variant/30"><span className="px-2 py-0.5 bg-secondary-container/20 text-secondary text-[10px] font-mono font-bold rounded-md border border-secondary/40 uppercase tracking-widest">{selectedNode ? 'Variable Node' : 'Node Index'}</span></div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {selectedNode ? (
            <>
              <h2 className="text-xl text-white">{selectedNode.name}</h2>
              <p className="text-xs text-on-surface-variant">{String(selectedNode.raw.latest_concept || '').trim() || '暂无概念定义'}</p>
              <div className="text-xs text-on-surface-variant">关联文献: {relatedPapers.join('、') || '-'}</div>
            </>
          ) : nodes.slice(0, 40).map((n) => (
            <button key={n.id} onClick={() => { setSelectedNodeId(n.id); setSelectedNodeLibraryId(String(n.library_id || activeLibraryId)); }} className="w-full text-left p-2 border border-outline-variant/20 rounded text-xs text-on-surface-variant hover:border-secondary">{n.name}</button>
          ))}
        </div>
        <div className="p-4 bg-primary-container/90 border-t border-outline-variant/20"><button onClick={() => setCurrentView('chat')} className="w-full bg-secondary hover:bg-secondary/90 text-white py-2.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2"><MessageCircle className="w-4 h-4" />Jump to Chat</button></div>
      </aside>
    </div>
  );
}
