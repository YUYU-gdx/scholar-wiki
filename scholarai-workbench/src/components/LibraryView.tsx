import { FileText, ExternalLink, Library, Layers, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
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

function firstTitle(v: Record<string, unknown>, paperId: string): string {
  const pretty = (s: string): string => String(s || '').replace(/\.pdf$/i, '').replace(/__/g, ' ').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
  const mdPath = String(v.source_md_path || '').trim();
  if (mdPath) {
    const stem = mdPath.split(/[\\/]/).pop()?.replace(/\.md$/i, '') || '';
    const p = pretty(stem);
    if (p) return p;
  }
  const display = String(v.display_title || '').trim();
  if (display) return pretty(display);
  const title = String(v.title || '').trim();
  if (title) return pretty(title);
  return pretty(paperId);
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
    setCurrentView,
    selectedLibraryIds,
  } = useApp();
  const [expandedPapers, setExpandedPapers] = useState<Record<string, boolean>>({});
  const [mode, setMode] = useState<Mode>(() => (localStorage.getItem(MODE_KEY) as Mode) || 'papers');
  const [paperFilesByScopedKey, setPaperFilesByScopedKey] = useState<Record<string, PaperFileStatus>>({});

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

    setPaperFilesByScopedKey((prev) => {
      const next: Record<string, PaperFileStatus> = {};
      for (const p of entries) {
        next[p.scopedKey] = prev[p.scopedKey] || { pdf: false, markdown: false, html: false, loading: true };
        next[p.scopedKey].loading = true;
      }
      return next;
    });

    (async () => {
      const next: Record<string, PaperFileStatus> = {};
      await Promise.all(entries.map(async (p) => {
        try {
          let files = await api.graph.paperFiles(p.paperId, p.libraryId);
          if (!files.files.pdf && !files.files.markdown && !files.files.html && p.rawPaperId && p.rawPaperId !== p.paperId) {
            files = await api.graph.paperFiles(p.rawPaperId, p.libraryId);
          }
          next[p.scopedKey] = {
            pdf: !!files.files.pdf,
            markdown: !!files.files.markdown,
            html: !!files.files.html,
            loading: false,
          };
        } catch {
          next[p.scopedKey] = { pdf: false, markdown: false, html: false, loading: false };
        }
      }));
      if (!cancelled) setPaperFilesByScopedKey(next);
    })();

    return () => { cancelled = true; };
  }, [paperList]);

  const setSelectedPaper = (paperId: string, libraryId: string) => {
    setSelectedPaperId(paperId);
    setSelectedPaperLibraryId(libraryId);
  };

  const openInReader = (paperId: string, libraryId: string, rawPaperId: string, preferredType: 'pdf' | 'markdown' | 'html' | null) => {
    setSelectedPaper(paperId, libraryId);
    setSelectedPaperRawId(rawPaperId || null);
    setSelectedPaperPreferredType(preferredType);
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
        <section className="space-y-3">
          {paperList.map((p) => {
            const expanded = !!expandedPapers[p.scopedKey];
            const previewVars = p.variables.slice(0, 5);
            const remain = Math.max(0, p.variables.length - 5);
            const detected = paperFilesByScopedKey[p.scopedKey];
            const hasPdf = !!detected?.pdf;
            const hasMd = !!detected?.markdown;
            const hasHtml = !!detected?.html;
            const loadingFiles = !detected || !!detected.loading;
            return (
              <div key={p.scopedKey} className="p-4 bg-surface-container-lowest border border-outline-variant rounded-xl">
                <div className="flex items-center justify-between gap-3">
                  <button onClick={() => setExpandedPapers((prev) => ({ ...prev, [p.scopedKey]: !prev[p.scopedKey] }))} className="flex items-center gap-2 text-left">
                    {expanded ? <ChevronDown className="w-4 h-4 text-outline" /> : <ChevronRight className="w-4 h-4 text-outline" />}
                    <div>
                      <div className="text-sm font-semibold text-on-surface">{p.title}</div>
                      <div className="text-xs text-on-surface-variant">{p.paperId}</div>
                    </div>
                  </button>
                  {loadingFiles ? (
                    <div className="w-6 h-6 rounded-full border border-outline-variant bg-surface-container flex items-center justify-center" title="加载中">
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-secondary" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      {hasPdf && <button onClick={() => openInReader(p.paperId, p.libraryId, p.rawPaperId, 'pdf')} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />PDF</button>}
                      {hasMd && <button onClick={() => openInReader(p.paperId, p.libraryId, p.rawPaperId, 'markdown')} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />MD</button>}
                      {hasHtml && <button onClick={() => openInReader(p.paperId, p.libraryId, p.rawPaperId, 'html')} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />HTML</button>}
                    </div>
                  )}
                </div>
                <div className="mt-2 text-xs text-on-surface-variant">变量: {previewVars.map((v) => v.label || v.name || v.id).join('、') || '无'}{remain > 0 && `（+${remain} 个已折叠）`}</div>
                {expanded && (
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                    {p.variables.map((v) => (
                      <button key={`${p.scopedKey}-${v.id}`} onClick={() => { setSelectedNodeId(v.id); setSelectedNodeLibraryId(String(v.library_id || p.libraryId)); setCurrentView('graph'); }} className="text-left p-2 bg-surface-container border border-outline-variant rounded-lg hover:border-secondary">
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
                    <td className="px-4 py-3 text-right"><button onClick={() => { setSelectedNodeId(row.id); setSelectedNodeLibraryId(row.libraryId); setCurrentView('reader'); }} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary">跳转</button></td>
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
