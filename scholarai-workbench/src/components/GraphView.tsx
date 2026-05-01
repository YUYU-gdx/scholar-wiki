import { useState, useEffect, useMemo, useRef } from 'react';
import { Compass, ZoomIn, ZoomOut, Rotate3D, Focus, MessageCircle, X, Search, Share2 } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { GraphNode, GraphEdge, SearchResponse } from '../types';

function nodeLabel(n: GraphNode): string {
  return n.label || n.name || n.id || 'node';
}

function escapeHtml(t: string): string {
  return String(t || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] || c));
}

export default function GraphView() {
  const { graphData, setGraphData, selectedNodeId, setSelectedNodeId, setCurrentView, graphLoading } = useApp();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [nodeDetail, setNodeDetail] = useState<string[]>([]);
  const [relationDetail, setRelationDetail] = useState<string[]>([]);
  const canvasRef = useRef<HTMLDivElement>(null);

  const visibleNodes = useMemo(() => {
    if (!graphData) return [];
    const validated = graphData.nodes.filter(
      n => String(n.type || '') === 'variable' && !!n.validated_variable && Number(n.relation_degree || 0) > 0
    );
    if (validated.length > 0) return validated;
    const withEdges = graphData.nodes.filter(n => String(n.type || '') === 'variable' && Number(n.relation_degree || 0) > 0);
    if (withEdges.length > 0) return withEdges;
    return graphData.nodes.filter(n => String(n.type || '') === 'variable');
  }, [graphData]);

  const selectedNode = useMemo(() => {
    if (!selectedNodeId || !graphData) return null;
    return visibleNodes.find(n => n.id === selectedNodeId) || null;
  }, [selectedNodeId, graphData, visibleNodes]);

  const edgesForNode = useMemo(() => {
    if (!selectedNodeId || !graphData) return [];
    return graphData.edges.filter(e => {
      const src = typeof e.source === 'object' ? e.source?.id : e.source;
      const tgt = typeof e.target === 'object' ? e.target?.id : e.target;
      return src === selectedNodeId || tgt === selectedNodeId;
    });
  }, [selectedNodeId, graphData]);

  const paperIdsForNode = useMemo(() => {
    const ids = new Set<string>();
    for (const e of edgesForNode) {
      if (e.paper_id) ids.add(String(e.paper_id));
    }
    return ids;
  }, [edgesForNode]);

  const rankedNodes = useMemo(() => {
    return [...visibleNodes]
      .map(n => ({
        node: n,
        relCount: graphData ? graphData.edges.filter(e => {
          const src = typeof e.source === 'object' ? e.source?.id : e.source;
          const tgt = typeof e.target === 'object' ? e.target?.id : e.target;
          return src === n.id || tgt === n.id;
        }).length : 0,
      }))
      .sort((a, b) => b.relCount - a.relCount || nodeLabel(a.node).localeCompare(nodeLabel(b.node), 'zh-Hans-CN'))
      .slice(0, 40);
  }, [visibleNodes, graphData]);

  useEffect(() => {
    if (!selectedNode) return;
    const name = nodeLabel(selectedNode);
    const concept = String(selectedNode.latest_concept || '').trim() || '暂无概念定义';
    const theories = Array.isArray(selectedNode.latest_theories) ? selectedNode.latest_theories.filter(Boolean) : [];
    const srcInfo = selectedNode.latest_concept_source || {};
    setNodeDetail([
      `<strong>${escapeHtml(name)}</strong>`,
      `变量概念：${escapeHtml(concept.slice(0, 100))}`,
      `相关理论：${escapeHtml(theories.slice(0, 3).join('；') || '暂无提取')}`,
      `来源论文：<code>${escapeHtml(String(srcInfo.paper_id || '-'))}</code>`,
      `来源年份：<code>${escapeHtml(String(srcInfo.publication_year ?? '-'))}</code>`,
    ]);
    const relLines: string[] = [];
    if (edgesForNode.length === 0) {
      relLines.push('该变量当前没有可连接关系。');
    } else {
      for (const e of edgesForNode.slice(0, 8)) {
        const s = typeof e.source === 'object' ? nodeLabel(e.source) : String(e.source);
        const t = typeof e.target === 'object' ? nodeLabel(e.target) : String(e.target);
        relLines.push(`${escapeHtml(s)} → ${escapeHtml(t)} (${escapeHtml(e.direction || 'unknown')})`);
      }
    }
    relLines.push(`提及论文：<code>${[...paperIdsForNode].slice(0, 8).map(escapeHtml).join('、') || '-'}</code>`);
    setRelationDetail(relLines);
  }, [selectedNode, edgesForNode, paperIdsForNode]);

  const doSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await api.graph.search(searchQuery, 'variable', 12);
      setSearchResults(res);
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  const selectAndJump = (node: GraphNode) => {
    setSelectedNodeId(node.id);
  };

  const jumpToChat = () => {
    setCurrentView('chat');
  };

  if (graphLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#020617]">
        <div className="text-center space-y-4">
          <div className="w-10 h-10 border-2 border-secondary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-on-surface-variant font-mono text-sm">Loading knowledge graph...</p>
        </div>
      </div>
    );
  }

  if (!graphData) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#020617]">
        <div className="text-center space-y-4">
          <p className="text-on-surface-variant font-mono text-sm">No graph data available.</p>
          <p className="text-outline text-xs">Ensure the backend server is running.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 relative flex overflow-hidden bg-[#020617]">
      {/* Search Overlay */}
      <div className={`absolute top-6 left-6 w-80 z-10 precision-shadow overflow-hidden transition-all duration-300 ${showSearch ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none -translate-y-2'}`}>
        <div className="bg-surface-container-low/60 backdrop-blur-xl border border-outline-variant/30 rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Compass className="w-4 h-4 text-secondary" />
            <span className="font-mono text-[10px] uppercase tracking-widest text-outline">Node Finder</span>
          </div>
          <div className="flex gap-2 mb-3">
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') doSearch(); }}
              placeholder="Search variables..."
              className="flex-1 bg-surface-container/10 border border-outline-variant/30 rounded-lg px-3 py-1.5 text-xs text-on-surface placeholder:text-outline focus:ring-1 focus:ring-secondary/30 outline-none"
            />
            <button onClick={doSearch} disabled={searching} className="bg-secondary/20 text-secondary px-3 py-1.5 rounded-lg text-xs font-bold hover:bg-secondary/30 transition-all">
              {searching ? '...' : 'Search'}
            </button>
          </div>
          {searchResults && (
            <div className="space-y-2 max-h-60 overflow-auto custom-scrollbar">
              {searchResults.results.map((r) => (
                <button
                  key={r.id}
                  onClick={() => {
                    const match = visibleNodes.find(n => n.id === r.id);
                    if (match) { selectAndJump(match); setShowSearch(false); }
                  }}
                  className="w-full text-left p-3 bg-surface-container/10 border border-outline-variant/30 rounded-xl hover:border-secondary/30 transition-all"
                >
                  <div className="text-xs font-bold text-on-surface-variant mb-1 truncate">{r.title || r.id}</div>
                  <div className="text-[10px] text-secondary/70 font-mono tracking-tight">Kind: {r.kind} · Score: {r.score?.toFixed(4)}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Toggle Search Button */}
      <button
        onClick={() => setShowSearch(!showSearch)}
        className="absolute top-6 left-6 z-20 bg-surface-container-low/60 backdrop-blur-xl border border-outline-variant/30 rounded-xl p-2.5 hover:bg-surface-container-low/80 transition-all"
      >
        <Search className="w-4 h-4 text-secondary" />
      </button>

      {/* Main Canvas */}
      <div className="flex-1 relative overflow-hidden flex flex-col">
        {/* HUD */}
        <div className="absolute top-6 left-16 right-[420px] z-10 flex items-center gap-3 pointer-events-none">
          <div className="flex items-center gap-2 bg-surface-container-low/60 backdrop-blur-xl border border-outline-variant/30 rounded-2xl px-4 py-2 pointer-events-auto">
            <span className="font-mono text-[10px] text-on-surface-variant">Nodes</span>
            <span className="font-mono text-sm font-bold text-on-surface">{visibleNodes.length}</span>
            <span className="w-px h-4 bg-outline-variant/30"></span>
            <span className="font-mono text-[10px] text-on-surface-variant">Edges</span>
            <span className="font-mono text-sm font-bold text-on-surface">{graphData.edges.length}</span>
            <span className="w-px h-4 bg-outline-variant/30"></span>
            <span className="font-mono text-[10px] text-on-surface-variant">Papers</span>
            <span className="font-mono text-sm font-bold text-on-surface">{graphData.meta?.paper_count ?? 0}</span>
          </div>
        </div>

        {/* Graph area placeholder – relies on 3D or fallback */}
        <div className="flex-1 flex items-center justify-center" ref={canvasRef}>
          <div className="text-center p-8 max-w-md">
            <Share2 className="w-12 h-12 text-secondary/30 mx-auto mb-4" />
            <p className="text-on-surface-variant text-sm mb-2">3D Graph Engine</p>
            <p className="text-outline text-xs font-mono">Connect a 3D renderer or use the node index panel to explore the graph.</p>
          </div>
        </div>

        {/* Bottom Toolbar */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-4 p-2 bg-surface-container-low/80 backdrop-blur-xl border border-outline-variant/30 rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.5)]">
          <div className="flex items-center border-r border-outline-variant/30 pr-4 mr-2 gap-1">
            <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
              <ZoomIn className="w-5 h-5" />
            </button>
            <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
              <ZoomOut className="w-5 h-5" />
            </button>
            <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
              <Rotate3D className="w-5 h-5" />
            </button>
            <button className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-surface-container text-outline hover:text-on-surface transition-all active:scale-95">
              <Focus className="w-5 h-5" />
            </button>
          </div>
          <div className="flex gap-6">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-secondary shadow-[0_0_8px_#14b8a6]"></div>
              <span className="text-[10px] text-outline-variant font-mono font-bold uppercase tracking-tight">POSITIVE</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_#f43f5e]"></div>
              <span className="text-[10px] text-outline-variant font-mono font-bold uppercase tracking-tight">NEGATIVE</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-violet-500 shadow-[0_0_8px_#8b5cf6]"></div>
              <span className="text-[10px] text-outline-variant font-mono font-bold uppercase tracking-tight">NON-LINEAR</span>
            </div>
          </div>
        </div>
      </div>

      {/* Detail Panel */}
      <aside className="w-[390px] bg-surface-container-lowest/10 backdrop-blur-2xl border-l border-outline-variant/30 flex flex-col overflow-hidden">
        <div className="p-5 border-b border-outline-variant/30">
          <div className="flex items-center justify-between mb-3">
            <span className="px-2 py-0.5 bg-secondary-container/20 text-secondary text-[10px] font-mono font-bold rounded-md border border-secondary/40 uppercase tracking-widest">
              {selectedNode ? 'Variable Node' : 'Node Index'}
            </span>
            {selectedNode && (
              <button onClick={() => setSelectedNodeId(null)} className="text-outline hover:text-on-surface transition-colors">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          {selectedNode ? (
            <h2 className="text-xl font-medium text-white mb-1">{nodeLabel(selectedNode)}</h2>
          ) : (
            <h2 className="text-xl font-medium text-white mb-1">Select a node</h2>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6 custom-scrollbar-dark">
          {selectedNode ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 border border-outline-variant/16 rounded-xl bg-surface-container/10">
                  <span className="text-[10px] text-outline block">Relations</span>
                  <strong className="text-sm text-on-surface">{edgesForNode.length}</strong>
                </div>
                <div className="p-3 border border-outline-variant/16 rounded-xl bg-surface-container/10">
                  <span className="text-[10px] text-outline block">Papers</span>
                  <strong className="text-sm text-on-surface">{paperIdsForNode.size}</strong>
                </div>
                <div className="p-3 border border-outline-variant/16 rounded-xl bg-surface-container/10">
                  <span className="text-[10px] text-outline block">Degree</span>
                  <strong className="text-sm text-on-surface">{selectedNode.relation_degree ?? '-'}</strong>
                </div>
              </div>

              <div>
                <h3 className="font-mono text-[10px] text-outline uppercase tracking-widest border-b border-outline-variant/10 pb-2 mb-3">Node Details</h3>
                <ul className="space-y-1.5 text-xs text-on-surface-variant">
                  {nodeDetail.map((line, i) => <li key={i} dangerouslySetInnerHTML={{ __html: line }} />)}
                </ul>
              </div>

              <div>
                <h3 className="font-mono text-[10px] text-outline uppercase tracking-widest border-b border-outline-variant/10 pb-2 mb-3">Relations</h3>
                <ul className="space-y-1.5 text-xs text-on-surface-variant">
                  {relationDetail.map((line, i) => <li key={i} dangerouslySetInnerHTML={{ __html: line }} />)}
                </ul>
              </div>

              {(graphData.isolated_nodes || []).filter(n => n.node_id === selectedNode.id).length > 0 && (
                <div>
                  <h3 className="font-mono text-[10px] text-outline uppercase tracking-widest border-b border-outline-variant/10 pb-2 mb-3">Isolation Info</h3>
                  <p className="text-xs text-on-surface-variant">
                    {graphData.isolated_nodes!.find(n => n.node_id === selectedNode.id)?.reason || 'Unknown'}
                  </p>
                </div>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-[10px] font-mono text-outline uppercase tracking-widest mb-3">Top Variables by Degree</p>
              {rankedNodes.map(({ node, relCount }) => (
                <button
                  key={node.id}
                  onClick={() => selectAndJump(node)}
                  className="w-full text-left p-3 bg-surface-container/10 border border-outline-variant/16 rounded-xl hover:border-secondary/30 transition-all"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-bold text-on-surface truncate">{nodeLabel(node)}</span>
                    <span className="text-[10px] text-secondary font-mono">{relCount}</span>
                  </div>
                  <p className="text-[10px] text-on-surface-variant truncate">{String(node.latest_concept || '').slice(0, 80) || 'No definition'}</p>
                </button>
              ))}
            </div>
          )}

          {(graphData.isolated_nodes || []).length > 0 && (
            <div>
              <h3 className="font-mono text-[10px] text-outline uppercase tracking-widest border-b border-outline-variant/10 pb-2 mb-3">
                Isolated Nodes ({graphData.isolated_nodes!.length})
              </h3>
              <div className="space-y-1 max-h-48 overflow-auto custom-scrollbar-dark">
                {graphData.isolated_nodes!.slice(0, 24).map(n => (
                  <div key={n.node_id} className="text-[11px] text-on-surface-variant py-1 px-2 border border-outline-variant/10 rounded-lg">
                    <strong className="text-on-surface">{n.label || n.node_id}</strong>
                    <span className="ml-2 text-outline">{n.reason || 'unknown'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="p-4 bg-primary-container/90 border-t border-outline-variant/20">
          <button onClick={jumpToChat} className="w-full bg-secondary hover:bg-secondary/90 text-white py-2.5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all shadow-lg shadow-secondary/20 active:scale-[0.98]">
            <MessageCircle className="w-4 h-4" />
            {selectedNodeId ? `Ask about "${selectedNode ? nodeLabel(selectedNode).slice(0, 20) : ''}"` : 'Jump to Chat'}
          </button>
        </div>
      </aside>
    </div>
  );
}