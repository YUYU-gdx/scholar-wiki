import { FileText, ExternalLink, Library, Layers, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useApp } from '../App';
import { api } from '../api';

const MODE_KEY = 'kn_graph_library_mode';

type Mode = 'papers' | 'variables';
type PaperFileAvailability = {
  pdf: boolean;
  markdown: boolean;
  html: boolean;
};
type PaperFileStatus = PaperFileAvailability & {
  loading: boolean;
};

type SelectionState = {
  pivot: number;
  focused: number;
  selected: Set<number>;
};

function createSelection(): SelectionState {
  return { pivot: 0, focused: 0, selected: new Set() };
}

function firstTitle(v: Record<string, unknown>, paperId: string): string {
  const pretty = (s: string): string => String(s || '').replace(/\.pdf$/i, '').replace(/__/g, ' ').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
  const display = String(v.display_title || '').trim();
  if (display) return pretty(display);
  const title = String(v.title || '').trim();
  if (title) return pretty(title);
  return pretty(paperId);
}

function metaLine(v: Record<string, unknown>): string {
  const authors = Array.isArray(v.authors_json)
    ? (v.authors_json as unknown[])
      .map((x) => {
        if (x && typeof x === 'object' && 'name' in (x as Record<string, unknown>)) {
          return String((x as Record<string, unknown>).name || '').trim();
        }
        if (typeof x === 'string') return x.trim();
        return '';
      })
      .filter(Boolean)
    : [];
  const authorText = authors.length ? authors.slice(0, 3).join('、') : '未知作者';
  const journal = String(v.journal || '').trim() || '未知期刊';
  const date = String(v.publication_date || '').trim() || (v.publication_year ? String(v.publication_year) : '未知时间');
  return `${authorText} | ${journal} | ${date}`;
}

export default function LibraryView() {
  const {
    graphData,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setSelectedPaperPreferredType,
    setSelectedNodeId,
    setSelectedNodeLibraryId,
    setSelectedPaperRawId,
    setReaderReturnView,
    setCurrentView,
    selectedLibraryIds,
    paperFileCache,
    setPaperFileCache,
  } = useApp();
  const [expandedPapers, setExpandedPapers] = useState<Record<string, boolean>>({});
  const [mode, setMode] = useState<Mode>(() => (localStorage.getItem(MODE_KEY) as Mode) || 'papers');
  const [paperFilesByScopedKey, setPaperFilesByScopedKey] = useState<Record<string, PaperFileStatus>>({});

  const selRef = useRef<SelectionState>(createSelection());
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; visible: boolean } | null>(null);
  const [, forceUpdate] = useReducer((x: number) => x + 1, 0);

  const deletePaper = async (p: { paperId: string; libraryId: string; scopedKey: string }) => {
    if (!confirm(`确定删除「${p.paperId}」吗？\n将同时删除数据库记录和磁盘文件。`)) return;
    try {
      await api.graph.deletePaper(p.paperId, p.libraryId);
      setPaperFilesByScopedKey((prev) => { const n = { ...prev }; delete n[p.scopedKey]; return n; });
      window.dispatchEvent(new CustomEvent('paper-deleted', { detail: { libraryId: p.libraryId } }));
    } catch { /* ignore */ }
  };

  const variables = useMemo(() => (graphData?.nodes || []).filter((n) => String(n.type || '') === 'variable'), [graphData]);

  const paperList = useMemo(() => {
    const paperMap = graphData?.paper_map || {};
    return Object.entries(paperMap).map(([scopedKey, detail]) => {
      const d = (detail || {}) as Record<string, unknown>;
      const mappedPaperId = String(d.paper_id || scopedKey.split('::').at(-1) || scopedKey).trim();
      const paperId = mappedPaperId.includes('::') ? String(mappedPaperId.split('::').at(-1) || mappedPaperId) : mappedPaperId;
      const rawPaperId = String(d.paper_id_raw || '').trim();
      const libraryId = String(d.library_id || scopedKey.split('::')[0] || '');
      const paperVars = variables.filter((v) => {
        const src = String(v.latest_concept_source?.paper_id || '');
        const dom = String(v.dominant_paper_id || '');
        return src === paperId || dom === paperId || (!!rawPaperId && (src === rawPaperId || dom === rawPaperId));
      });
      return {
        scopedKey,
        paperId,
        rawPaperId,
        libraryId,
        title: firstTitle(d, paperId),
        metaLine: metaLine(d),
        sourcePdfName: String(d.source_pdf_name || ''),
        variables: paperVars,
      };
    }).sort((a, b) => a.paperId.localeCompare(b.paperId));
  }, [graphData, variables]);

  useEffect(() => {
    let cancelled = false;
    const entries = paperList.map((p) => ({
      scopedKey: p.scopedKey,
      paperId: p.paperId,
      rawPaperId: p.rawPaperId,
      libraryId: p.libraryId,
    }));
    if (!entries.length) {
      setPaperFilesByScopedKey({});
      return () => { cancelled = true; };
    }

    setPaperFilesByScopedKey(() => {
      const next: Record<string, PaperFileStatus> = {};
      for (const p of entries) {
        const cached = paperFileCache[p.scopedKey];
        if (cached?.loaded) {
          next[p.scopedKey] = {
            pdf: !!cached.pdf,
            markdown: !!cached.markdown,
            html: !!cached.html,
            loading: false,
          };
        } else {
          next[p.scopedKey] = { pdf: false, markdown: false, html: false, loading: true };
        }
      }
      return next;
    });

    (async () => {
      const toFetch = entries.filter((p) => !paperFileCache[p.scopedKey]?.loaded);
      if (!toFetch.length) return;
      const fetchedCache: Record<string, { pdf: boolean; markdown: boolean; html: boolean; loaded: boolean }> = {};
      const fetchedLocal: Record<string, PaperFileStatus> = {};
      await Promise.all(toFetch.map(async (p) => {
        try {
          let files = await api.graph.paperFiles(p.paperId, p.libraryId);
          if (!files.files.pdf && !files.files.markdown && !files.files.html && p.rawPaperId && p.rawPaperId !== p.paperId) {
            files = await api.graph.paperFiles(p.rawPaperId, p.libraryId);
          }
          fetchedLocal[p.scopedKey] = {
            pdf: !!files.files.pdf,
            markdown: !!files.files.markdown,
            html: !!files.files.html,
            loading: false,
          };
          fetchedCache[p.scopedKey] = {
            pdf: !!files.files.pdf,
            markdown: !!files.files.markdown,
            html: !!files.files.html,
            loaded: true,
          };
        } catch {
          fetchedLocal[p.scopedKey] = { pdf: false, markdown: false, html: false, loading: false };
          fetchedCache[p.scopedKey] = { pdf: false, markdown: false, html: false, loaded: true };
        }
      }));
      if (!cancelled) {
        setPaperFileCache((prev) => ({ ...prev, ...fetchedCache }));
        setPaperFilesByScopedKey((prev) => ({ ...prev, ...fetchedLocal }));
      }
    })();

    return () => { cancelled = true; };
  }, [paperList, paperFileCache, setPaperFileCache]);

  // ── Selection logic ──

  const isSelected = useCallback((index: number) => {
    return selRef.current.selected.has(index);
  }, []);

  const select = useCallback((index: number) => {
    const s = selRef.current;
    s.selected.clear();
    s.selected.add(index);
    s.pivot = index;
    s.focused = index;
    forceUpdate();
  }, []);

  const toggleSelect = useCallback((index: number) => {
    const s = selRef.current;
    if (s.selected.has(index)) {
      s.selected.delete(index);
    } else {
      s.selected.add(index);
    }
    s.pivot = index;
    s.focused = index;
    forceUpdate();
  }, []);

  const shiftSelect = useCallback((index: number) => {
    const s = selRef.current;
    s.selected.clear();
    const from = Math.min(index, s.pivot);
    const to = Math.max(index, s.pivot);
    for (let i = from; i <= to; i++) {
      s.selected.add(i);
    }
    s.focused = index;
    forceUpdate();
  }, []);

  const selectAll = useCallback(() => {
    const s = selRef.current;
    s.selected.clear();
    for (let i = 0; i < paperList.length; i++) {
      s.selected.add(i);
    }
    forceUpdate();
  }, [paperList]);

  const clearSelection = useCallback(() => {
    const s = selRef.current;
    s.selected.clear();
    forceUpdate();
  }, []);

  const getSelectedPapers = useCallback(() => {
    return Array.from(selRef.current.selected).map((i) => paperList[i]).filter(Boolean);
  }, [paperList]);

  // ── Existing helpers ──

  const setSelectedPaper = (paperId: string, libraryId: string) => {
    setSelectedPaperId(paperId);
    setSelectedPaperLibraryId(libraryId);
  };

  const openInReader = (paperId: string, libraryId: string, rawPaperId: string, preferredType: 'pdf' | 'markdown' | 'html' | null) => {
    setSelectedPaper(paperId, libraryId);
    setSelectedPaperRawId(rawPaperId || null);
    setSelectedPaperPreferredType(preferredType);
    setReaderReturnView('library');
    setCurrentView('reader');
  };

  const variableRows = useMemo(() => {
    return variables.map((v) => ({
      id: v.id,
      libraryId: String(v.library_id || ''),
      name: v.label || v.name || v.id,
      concept: String(v.latest_concept || '').trim() || '暂无概念定义',
      sourcePaperId: String(v.latest_concept_source?.paper_id || v.dominant_paper_id || '-'),
    })).sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
  }, [variables]);

  const openVariableSourceInReader = (row: { id: string; libraryId: string; sourcePaperId: string }) => {
    const sourcePaperId = String(row.sourcePaperId || '').trim();
    const hit = paperList.find((p) => (
      p.libraryId === row.libraryId && (
        p.paperId === sourcePaperId ||
        p.rawPaperId === sourcePaperId ||
        sourcePaperId === p.scopedKey.split('::').at(-1)
      )
    ));
    if (hit) {
      openInReader(hit.paperId, hit.libraryId, hit.rawPaperId, null);
      return;
    }
    setSelectedNodeId(row.id);
    setSelectedNodeLibraryId(row.libraryId);
    if (sourcePaperId && sourcePaperId !== '-') {
      setSelectedPaperId(sourcePaperId);
      setSelectedPaperLibraryId(row.libraryId);
      setSelectedPaperRawId(sourcePaperId);
      setSelectedPaperPreferredType(null);
    }
    setReaderReturnView('library');
    setCurrentView('reader');
  };

  const setLibraryMode = (next: Mode) => {
    setMode(next);
    localStorage.setItem(MODE_KEY, next);
  };

  return (
    <div className="flex-1 overflow-auto px-8 py-6 space-y-6">
      <div className="flex items-center gap-3">
        <Library className="w-5 h-5 text-secondary" />
        <h2 className="text-2xl font-medium tracking-tight text-on-surface">Research Library</h2>
        <span className="text-[10px] font-mono font-bold text-outline-variant bg-surface-container px-2 py-0.5 rounded">Selected: {selectedLibraryIds.join(', ')}</span>
      </div>

      <div className="flex items-center gap-2 p-1 bg-surface-container-low w-fit rounded-xl border border-outline-variant">
        <button onClick={() => setLibraryMode('papers')} className={`px-4 py-1.5 text-xs font-bold rounded-lg ${mode === 'papers' ? 'bg-surface-container-lowest text-on-surface' : 'text-outline'}`}>Papers</button>
        <button onClick={() => setLibraryMode('variables')} className={`px-4 py-1.5 text-xs font-bold rounded-lg ${mode === 'variables' ? 'bg-surface-container-lowest text-on-surface' : 'text-outline'}`}>Variables</button>
      </div>

      {mode === 'papers' && (
        <section
          className="space-y-3"
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
              e.preventDefault();
              selectAll();
            }
            if (e.key === 'Escape') {
              clearSelection();
              setCtxMenu(null);
            }
          }}
          tabIndex={-1}
        >
          {paperList.map((p, idx) => {
            const expanded = !!expandedPapers[p.scopedKey];
            const previewVars = p.variables.slice(0, 5);
            const remain = Math.max(0, p.variables.length - 5);
            const detected = paperFilesByScopedKey[p.scopedKey];
            const hasPdf = !!detected?.pdf;
            const hasMd = !!detected?.markdown;
            const loadingFiles = !detected || !!detected.loading;
            return (
              <div
                key={p.scopedKey}
                className={`p-4 bg-surface-container-lowest border border-outline-variant rounded-xl ${isSelected(idx) ? 'ring-2 ring-secondary' : ''}`}
                onClick={(e) => {
                  if (e.shiftKey) shiftSelect(idx);
                  else if (e.ctrlKey || e.metaKey) toggleSelect(idx);
                  else select(idx);
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  if (!isSelected(idx)) select(idx);
                  setCtxMenu({ x: e.clientX, y: e.clientY, visible: true });
                }}
              >
                <div className="flex items-center justify-between gap-3">
                  <button onClick={(e) => (e.stopPropagation(), setExpandedPapers((prev) => ({ ...prev, [p.scopedKey]: !prev[p.scopedKey] })))} className="flex items-center gap-2 text-left">
                    {expanded ? <ChevronDown className="w-4 h-4 text-outline" /> : <ChevronRight className="w-4 h-4 text-outline" />}
                      <div>
                        <div className="text-sm font-semibold text-on-surface">{p.title}</div>
                      <div className="text-xs text-on-surface-variant">{p.metaLine}</div>
                      </div>
                  </button>
                  {loadingFiles ? (
                    <div className="w-6 h-6 rounded-full border border-outline-variant bg-surface-container flex items-center justify-center" title="加载中">
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-secondary" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      {hasPdf && <button onClick={(e) => (e.stopPropagation(), openInReader(p.paperId, p.libraryId, p.rawPaperId, 'pdf'))} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />PDF</button>}
                      {hasMd && <button onClick={(e) => (e.stopPropagation(), openInReader(p.paperId, p.libraryId, p.rawPaperId, 'markdown'))} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />MD</button>}
                      <button onClick={(e) => (e.stopPropagation(), deletePaper(p))} className="text-xs px-2 py-1 rounded border border-red-200 hover:border-red-400 hover:bg-red-50 text-red-600 flex items-center gap-1">删除</button>
                    </div>
                  )}
                </div>
                <div className="mt-2 text-xs text-on-surface-variant">变量: {previewVars.map((v) => v.label || v.name || v.id).join('、') || '无'}{remain > 0 && `（+${remain} 个已折叠）`}</div>
                {expanded && (
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                    {p.variables.map((v) => (
                      <button key={`${p.scopedKey}-${v.id}`} onClick={(e) => (e.stopPropagation(), setSelectedNodeId(v.id), setSelectedNodeLibraryId(String(v.library_id || p.libraryId)), setCurrentView('graph'))} className="text-left p-2 bg-surface-container border border-outline-variant rounded-lg hover:border-secondary">
                        <div className="text-xs font-semibold text-on-surface truncate">{v.label || v.name || v.id}</div>
                        <div className="text-[11px] text-on-surface-variant truncate">{String(v.latest_concept || '').slice(0, 60) || '暂无概念'}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      )}

      {mode === 'papers' && ctxMenu?.visible && (() => {
        const papers = Array.from(selRef.current.selected).map((i) => paperList[i]).filter(Boolean);
        const hasPdf = papers.some((p) => paperFilesByScopedKey[p.scopedKey]?.pdf);
        const hasMd = papers.some((p) => paperFilesByScopedKey[p.scopedKey]?.markdown);
        const allExpanded = papers.every((p) => expandedPapers[p.scopedKey]);
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setCtxMenu(null)} />
            <div
              className="fixed z-50 bg-surface-container-lowest border border-outline-variant rounded-xl shadow-lg py-1 min-w-[180px]"
              style={{ left: ctxMenu.x, top: ctxMenu.y }}
            >
              {hasPdf && (
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                  onClick={() => {
                    const first = papers.find((p) => paperFilesByScopedKey[p.scopedKey]?.pdf);
                    if (first) openInReader(first.paperId, first.libraryId, first.rawPaperId, 'pdf');
                    setCtxMenu(null);
                  }}
                >
                  在阅读器中打开 (PDF)
                </button>
              )}
              {hasMd && (
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                  onClick={() => {
                    const first = papers.find((p) => paperFilesByScopedKey[p.scopedKey]?.markdown);
                    if (first) openInReader(first.paperId, first.libraryId, first.rawPaperId, 'markdown');
                    setCtxMenu(null);
                  }}
                >
                  在阅读器中打开 (MD)
                </button>
              )}
              <button
                className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                onClick={() => {
                  const toExpand = !allExpanded;
                  setExpandedPapers((prev) => {
                    const next = { ...prev };
                    for (const p of papers) {
                      next[p.scopedKey] = toExpand;
                    }
                    return next;
                  });
                  setCtxMenu(null);
                }}
              >
                {allExpanded ? '折叠' : '展开'} ({papers.length} 篇)
              </button>
              <div className="border-t border-outline-variant my-1" />
              <button
                className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                onClick={async () => {
                  const n = papers.length;
                  const names = papers.map((p) => p.paperId).join(', ');
                  if (!confirm(`确定删除 ${n} 篇论文吗？\n${names}\n将同时删除数据库记录和磁盘文件。`)) return;
                  let ok = 0;
                  let fail = 0;
                  await Promise.allSettled(papers.map((p) =>
                    api.graph.deletePaper(p.paperId, p.libraryId).then(() => { ok++; })
                  ));
                  fail = n - ok;
                  setPaperFilesByScopedKey((prev) => {
                    const next2 = { ...prev };
                    for (const p of papers) delete next2[p.scopedKey];
                    return next2;
                  });
                  for (const p of papers) {
                    window.dispatchEvent(new CustomEvent('paper-deleted', { detail: { libraryId: p.libraryId } }));
                  }
                  clearSelection();
                  setCtxMenu(null);
                  if (fail > 0) alert(`已删除 ${ok} 篇${fail > 0 ? `，${fail} 篇失败` : ''}`);
                }}
              >
                删除 ({papers.length} 篇)
              </button>
            </div>
          </>
        );
      })()}

      {mode === 'variables' && (
        <section>
          <div className="flex items-center gap-3 mb-4">
            <Layers className="w-5 h-5 text-secondary" />
            <h3 className="text-xl font-medium text-on-surface">Variables and Concepts</h3>
          </div>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
            <table className="w-full text-left border-collapse">
              <thead className="bg-surface-container-low border-b border-outline-variant"><tr><th className="px-4 py-3 text-[11px] font-mono uppercase text-outline">Variable</th><th className="px-4 py-3 text-[11px] font-mono uppercase text-outline">Concept</th><th className="px-4 py-3 text-[11px] font-mono uppercase text-outline">Source Paper</th><th className="px-4 py-3" /></tr></thead>
              <tbody className="divide-y divide-outline-variant">
                {variableRows.map((row) => (
                  <tr key={`${row.libraryId}-${row.id}`} className="hover:bg-surface-container-low transition-colors">
                    <td className="px-4 py-3 text-sm text-on-surface font-medium">{row.name}</td>
                    <td className="px-4 py-3 text-xs text-on-surface-variant">{row.concept}</td>
                    <td className="px-4 py-3 text-xs font-mono text-on-surface-variant">{row.sourcePaperId}</td>
                    <td className="px-4 py-3 text-right"><button onClick={() => openVariableSourceInReader(row)} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary">跳转</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
