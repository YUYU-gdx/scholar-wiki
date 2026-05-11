import { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../app-context';
import { api } from '../api';
import type { SemanticNeighborResultItem, SemanticVariableMatch } from '../types';

export default function GraphView() {
  const iframeRevRef = useRef<string>(String(Date.now()));
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  const {
    activeLibraryId,
    selectedLibraryIds,
    selectedNodeId,
    selectedNodeLibraryId,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setSelectedPaperPreferredType,
    setSelectedPaperRawId,
    setReaderReturnView,
    setCurrentView,
  } = useApp();

  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);
  const [searching, setSearching] = useState(false);
  const [loadingNeighborsFor, setLoadingNeighborsFor] = useState('');
  const [searchResult, setSearchResult] = useState<SemanticVariableMatch[]>([]);
  const [neighborsByKey, setNeighborsByKey] = useState<Record<string, SemanticNeighborResultItem[]>>({});
  const [errorText, setErrorText] = useState('');
  const [activeKey, setActiveKey] = useState('');

  useEffect(() => {
    function onMessage(evt: MessageEvent) {
      const data = evt.data as { type?: string; payload?: Record<string, unknown> } | null;
      if (!data || typeof data !== 'object') return;

      if (data.type === 'KN_GRAPH_OPEN_READER') {
        const paperId = String(data.payload?.paperId || '');
        const libraryId = String(data.payload?.libraryId || activeLibraryId || 'supply_chain');
        if (!paperId) return;
        const rawType = String(data.payload?.preferredType || '');
        const preferredType = (['pdf', 'markdown', 'html'].includes(rawType))
          ? rawType as 'pdf' | 'markdown' | 'html'
          : null;
        setSelectedPaperId(paperId);
        setSelectedPaperLibraryId(libraryId);
        setSelectedPaperPreferredType(preferredType);
        setSelectedPaperRawId(String(data.payload?.rawPaperId || '') || null);
        setReaderReturnView('graph');
        setCurrentView('reader');
        return;
      }

    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [
    activeLibraryId,
    selectedLibraryIds,
    setCurrentView,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setSelectedPaperPreferredType,
    setSelectedPaperRawId,
    setReaderReturnView,
  ]);

  const src = useMemo(() => {
    const ids = selectedLibraryIds.length ? selectedLibraryIds : [activeLibraryId || 'supply_chain'];
    const qs = new URLSearchParams();
    qs.set('library_id', activeLibraryId || ids[0] || 'supply_chain');
    qs.set('active_library_id', activeLibraryId || ids[0] || 'supply_chain');
    qs.set('library_ids', ids.join(','));
    if (selectedNodeId) qs.set('selected_node_id', selectedNodeId);
    if (selectedNodeLibraryId) qs.set('selected_node_library_id', selectedNodeLibraryId);
    qs.set('ui_rev', iframeRevRef.current);
    return `/frontend_legacy/graph_3d/index.html?${qs.toString()}`;
  }, [activeLibraryId, selectedLibraryIds]);

  const libraryIds = useMemo(() => {
    const ids = selectedLibraryIds.length ? selectedLibraryIds : [activeLibraryId || 'supply_chain'];
    return ids.filter(Boolean);
  }, [activeLibraryId, selectedLibraryIds, selectedNodeId, selectedNodeLibraryId]);

  const focusGraphNode = (nodeId: string, variableName: string, libraryId?: string) => {
    const frame = iframeRef.current;
    if (!frame?.contentWindow) return;
    frame.contentWindow.postMessage({
      type: 'KN_GRAPH_FOCUS_NODE',
      payload: {
        nodeId,
        variableName,
        libraryId: libraryId || '',
      },
    }, '*');
    setExpanded(false);
  };

  const doSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setErrorText('');
    setNeighborsByKey({});
    setActiveKey('');
    try {
      const res = await api.graph.semanticVariableSearch(q, Math.max(3, Math.min(20, topK)), libraryIds);
      setSearchResult(res.matched_variables || []);
      setExpanded(true);
    } catch (err) {
      setErrorText(String((err as Error)?.message || err));
      setSearchResult([]);
    } finally {
      setSearching(false);
    }
  };

  const loadNeighbors = async (row: SemanticVariableMatch) => {
    const key = `${row.library_id}::${row.variable_name}`;
    setActiveKey(key);
    if (neighborsByKey[key]) return;
    setLoadingNeighborsFor(key);
    try {
      const res = await api.graph.semanticVariableNeighbors(row.variable_name, Math.max(3, Math.min(20, topK)), [row.library_id]);
      setNeighborsByKey((prev) => ({ ...prev, [key]: res.results || [] }));
    } catch (err) {
      setErrorText(String((err as Error)?.message || err));
    } finally {
      setLoadingNeighborsFor('');
    }
  };

  return (
    <div className="flex-1 bg-surface-container-low relative">
      <div className={`absolute top-3 left-4 right-4 lg:right-[30rem] z-30 rounded-2xl border border-secondary/20 bg-surface-container-lowest/95 backdrop-blur shadow-2xl shadow-black/10 transition-all ${expanded ? 'max-h-[64vh]' : 'max-h-12'} overflow-hidden`}>
        <div className="h-12 px-3 flex items-center gap-2 border-b border-outline-variant/30 bg-linear-to-r from-secondary-container/20 to-surface-container-lowest">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="px-2.5 py-1 rounded-lg border border-outline-variant text-xs font-mono hover:border-secondary bg-surface-container"
          >
            {expanded ? '收起检索' : '展开检索'}
          </button>
          <div className="text-[11px] font-mono text-outline-variant hidden md:block">Variable Semantic Search</div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void doSearch(); }}
            placeholder="输入变量语义，例如：resilience under uncertainty"
            className="flex-1 bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-sm outline-none focus:border-secondary"
          />
          <input
            type="number"
            min={3}
            max={20}
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value || 5))}
            className="w-20 bg-surface-container border border-outline-variant rounded-lg px-2 py-1.5 text-sm outline-none focus:border-secondary"
          />
          <button
            onClick={() => void doSearch()}
            disabled={searching}
            className="px-3 py-1.5 rounded-lg bg-secondary text-on-secondary text-sm font-semibold disabled:opacity-60"
          >
            {searching ? '检索中...' : '检索'}
          </button>
        </div>

        <div className="p-3 overflow-y-auto max-h-[calc(64vh-3rem)]">
          {!!errorText && <div className="mb-3 text-xs text-error bg-error-container/20 border border-error/30 rounded p-2">{errorText}</div>}
          {searchResult.length === 0 ? (
            <div className="text-sm text-on-surface-variant px-1 py-2">暂无检索结果。输入 query 后点击「检索」。</div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between px-1">
                <div className="text-xs font-mono uppercase tracking-wider text-outline-variant">Matched Variables</div>
                <div className="text-[11px] text-outline">共 {searchResult.length} 条</div>
              </div>
              {searchResult.map((row) => {
                const key = `${row.library_id}::${row.variable_name}`;
                const neighborSets = neighborsByKey[key] || [];
                const active = activeKey === key;
                return (
                  <div key={`${row.id}-${key}`} className={`rounded-2xl border p-3 transition-all ${active ? 'border-secondary/50 bg-secondary-container/10' : 'border-outline-variant bg-surface-container'}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-semibold text-on-surface truncate">{row.variable_name || row.node_id || '-'}</div>
                        <div className="text-[10px] mt-1 inline-flex px-2 py-0.5 rounded bg-secondary-container/20 text-secondary font-mono">{row.library_id}</div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          onClick={() => void loadNeighbors(row)}
                          className="text-xs px-2.5 py-1 rounded-lg border border-outline-variant hover:border-secondary bg-surface-container"
                        >
                          查看前后因
                        </button>
                        {row.node_id && (
                          <button
                            onClick={() => focusGraphNode(row.node_id, row.variable_name, row.library_id)}
                            className="text-xs px-2.5 py-1 rounded-lg bg-secondary text-on-secondary"
                          >
                            跳转图谱
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="text-xs text-on-surface-variant mt-2 line-clamp-3">{row.concept_text || '暂无概念'}</div>
                    <div className="mt-2">
                      {loadingNeighborsFor === key && <div className="text-xs text-on-surface-variant">正在加载前后因...</div>}
                      {neighborSets.map((group, idx) => (
                        <div key={`${key}-${idx}`} className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                          <div className="rounded-xl border border-emerald-300/40 p-2 bg-emerald-50/30">
                            <div className="text-[11px] font-mono uppercase text-emerald-700 mb-1">Causes / 前因</div>
                            <div className="space-y-1">
                              {group.cause_variables.length === 0 && <div className="text-[11px] text-on-surface-variant">无前因变量</div>}
                              {group.cause_variables.map((v) => (
                                <button key={`${v.library_id}-${v.node_id}-c`} onClick={() => focusGraphNode(v.node_id, v.variable_name, v.library_id)} className="w-full text-left rounded-lg border border-outline-variant/30 px-2 py-1 hover:border-secondary bg-white/70">
                                  <div className="text-xs font-semibold">{v.variable_name}</div>
                                  <div className="text-[11px] text-on-surface-variant line-clamp-2">{v.concept_text || '暂无概念'}</div>
                                </button>
                              ))}
                            </div>
                          </div>
                          <div className="rounded-xl border border-sky-300/40 p-2 bg-sky-50/30">
                            <div className="text-[11px] font-mono uppercase text-sky-700 mb-1">Effects / 后果</div>
                            <div className="space-y-1">
                              {group.effect_variables.length === 0 && <div className="text-[11px] text-on-surface-variant">无后果变量</div>}
                              {group.effect_variables.map((v) => (
                                <button key={`${v.library_id}-${v.node_id}-e`} onClick={() => focusGraphNode(v.node_id, v.variable_name, v.library_id)} className="w-full text-left rounded-lg border border-outline-variant/30 px-2 py-1 hover:border-secondary bg-white/70">
                                  <div className="text-xs font-semibold">{v.variable_name}</div>
                                  <div className="text-[11px] text-on-surface-variant line-clamp-2">{v.concept_text || '暂无概念'}</div>
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <iframe ref={iframeRef} title="Legacy Graph 3D" src={src} className="w-full h-full border-0" />
    </div>
  );
}
