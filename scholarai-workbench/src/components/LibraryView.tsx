import { Filter, Search, CloudUpload, FileText, ExternalLink, Link2 } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useApp } from '../App';
import { api } from '../api';
import type { PaperDetail } from '../types';

export default function LibraryView() {
  const { activeLibraryId, libraries, setSelectedPaperId, setCurrentView } = useApp();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMode, setSearchMode] = useState<'variable' | 'paper'>('variable');
  const [searchResults, setSearchResults] = useState<Array<{ id: string; kind: string; title?: string; score: number }>>([]);
  const [searching, setSearching] = useState(false);
  const [selectedPaper, setSelectedPaper] = useState<PaperDetail | null>(null);
  const [litSearchQuery, setLitSearchQuery] = useState('');
  const [litSearchResults, setLitSearchResults] = useState<{
    keyword_hits: unknown[];
    rag_hits: unknown[];
    merged_hits: unknown[];
    degraded?: boolean;
  } | null>(null);
  const [litSearching, setLitSearching] = useState(false);

  const doSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await api.graph.search(searchQuery, searchMode, 20);
      setSearchResults(res.results || []);
    } catch { /* ignore */ }
    finally { setSearching(false); }
  };

  const doLitSearch = async () => {
    if (!litSearchQuery.trim()) return;
    setLitSearching(true);
    try {
      const res = await api.literature.search(litSearchQuery, activeLibraryId);
      setLitSearchResults(res);
    } catch { /* ignore */ }
    finally { setLitSearching(false); }
  };

  const openPaper = async (paperId: string) => {
    try {
      const paper = await api.graph.paper(paperId);
      setSelectedPaper(paper);
      setSelectedPaperId(paperId);
    } catch { /* ignore */ }
  };

  const activeLib = libraries.find(l => l.library_id === activeLibraryId);

  return (
    <div className="flex-1 flex overflow-hidden">
      <section className="flex-1 overflow-auto px-8 py-6">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-medium tracking-tight text-on-surface font-sans">Research Library</h2>
            {activeLib && (
              <span className="text-[10px] font-mono font-bold text-outline-variant bg-surface-container px-2 py-0.5 rounded">
                {activeLib.library_id.toUpperCase()} · {activeLib.paper_count} PAPERS
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 mb-4">
          <div className="flex items-center gap-1 p-1 bg-surface-container-low w-fit rounded-xl border border-outline-variant">
            <button
              onClick={() => setSearchMode('variable')}
              className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${searchMode === 'variable' ? 'bg-surface-container-lowest text-on-surface precision-shadow' : 'text-outline hover:text-on-surface-variant'}`}
            >
              Variables
            </button>
            <button
              onClick={() => setSearchMode('paper')}
              className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${searchMode === 'paper' ? 'bg-surface-container-lowest text-on-surface precision-shadow' : 'text-outline hover:text-on-surface-variant'}`}
            >
              Papers
            </button>
          </div>
          <div className="relative flex-1 max-w-md group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-outline group-focus-within:text-secondary transition-colors" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') doSearch(); }}
              placeholder={`Search ${searchMode === 'variable' ? 'variables' : 'papers'}...`}
              className="w-full bg-surface-container border border-outline-variant rounded-lg px-10 py-2 text-sm font-mono focus:ring-1 focus:ring-secondary/30 outline-none transition-all placeholder:text-outline"
            />
          </div>
          <button onClick={doSearch} disabled={searching} className="bg-secondary text-on-secondary px-4 py-2 rounded-lg text-xs font-bold hover:opacity-90 transition-all flex items-center gap-2 disabled:opacity-50">
            <Search className="w-3.5 h-3.5" />
            {searching ? 'Searching...' : 'Search'}
          </button>
        </div>

        {searchResults.length > 0 && (
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden glass-shadow mb-8">
            <table className="w-full text-left border-collapse">
              <thead className="bg-surface-container-low border-b border-outline-variant">
                <tr>
                  <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Name</th>
                  <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Kind</th>
                  <th className="px-4 py-3 text-[11px] font-mono uppercase tracking-widest text-outline">Score</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant">
                {searchResults.map((item) => (
                  <tr key={`${item.kind}-${item.id}`} className="hover:bg-surface-container-low transition-colors cursor-pointer group"
                    onClick={() => {
                      if (item.kind === 'paper' || searchMode === 'paper') {
                        openPaper(item.id);
                      } else {
                        setCurrentView('graph');
                      }
                    }}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-outline-variant group-hover:text-secondary transition-colors" />
                        <span className="font-medium text-on-surface text-sm truncate max-w-xs">{item.title || item.id}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-on-surface-variant font-mono">{item.kind}</td>
                    <td className="px-4 py-3 text-xs text-secondary font-mono font-bold">{item.score?.toFixed(4)}</td>
                    <td className="px-4 py-3 text-right">
                      <ExternalLink className="w-4 h-4 text-outline group-hover:text-secondary transition-colors opacity-0 group-hover:opacity-100" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="border-t border-outline-variant pt-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-on-surface">Literature Search</h3>
            <span className="text-[10px] font-mono text-outline-variant uppercase tracking-widest">RAG + BM25</span>
          </div>
          <div className="flex gap-2 mb-4">
            <div className="relative flex-1 group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-outline group-focus-within:text-secondary transition-colors" />
              <input
                value={litSearchQuery}
                onChange={(e) => setLitSearchQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') doLitSearch(); }}
                placeholder="Ask about your literature..."
                className="w-full bg-surface-container border border-outline-variant rounded-lg px-10 py-2 text-sm font-mono focus:ring-1 focus:ring-secondary/30 outline-none transition-all placeholder:text-outline"
              />
            </div>
            <button onClick={doLitSearch} disabled={litSearching} className="bg-secondary text-on-secondary px-4 py-2 rounded-lg text-xs font-bold hover:opacity-90 transition-all flex items-center gap-2 disabled:opacity-50">
              <Search className="w-3.5 h-3.5" />
              {litSearching ? '...' : 'Search'}
            </button>
          </div>

          {litSearchResults && (
            <div className="space-y-4">
              {litSearchResults.degraded && (
                <div className="bg-error-container/10 border border-error/20 rounded-xl p-3 text-sm text-error">
                  Literature service unavailable — showing limited results.
                </div>
              )}
              {Array.isArray(litSearchResults.merged_hits) && litSearchResults.merged_hits.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-mono uppercase text-outline tracking-widest">Merged Results ({litSearchResults.merged_hits.length})</h4>
                  {litSearchResults.merged_hits.slice(0, 10).map((hit: Record<string, unknown>, i) => (
                    <div key={i} className="p-4 bg-surface-container-lowest border border-outline-variant rounded-xl hover:border-secondary transition-all precision-shadow">
                      <p className="text-sm text-on-surface mb-1">{String(hit.sentence || hit.title || hit.paper_id || '').slice(0, 200)}</p>
                      <div className="flex items-center gap-2 text-[10px] text-outline font-mono">
                        {hit.paper_id && <span>{String(hit.paper_id)}</span>}
                        {hit.score && <span>score: {Number(hit.score).toFixed(4)}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <aside className="w-80 border-l border-outline-variant bg-surface-container-lowest flex flex-col p-6 overflow-y-auto">
        {selectedPaper ? (
          <>
            <div className="mb-6 flex justify-between items-start">
              <span className="bg-secondary-container/30 text-secondary px-2 py-1 rounded text-[10px] font-mono uppercase tracking-widest font-bold border border-secondary/20">Paper Detail</span>
            </div>
            <div className="space-y-6">
              <section>
                <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-2">Title</h3>
                <h4 className="text-lg font-medium text-on-surface leading-tight font-sans">{selectedPaper.title || selectedPaper.paper_id}</h4>
                {selectedPaper.doi && <p className="text-[13px] text-on-surface-variant mt-1 font-mono">{selectedPaper.doi}</p>}
              </section>

              {selectedPaper.extractability_status && (
                <section className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Extraction Status</h3>
                  <span className={`text-[10px] font-mono font-bold uppercase px-2 py-1 rounded ${selectedPaper.extractability_status === 'yes' ? 'bg-secondary-container/20 text-secondary' : 'bg-surface-container text-on-surface-variant'}`}>
                    {selectedPaper.extractability_status}
                  </span>
                  {selectedPaper.paper_type && <p className="text-xs text-on-surface-variant mt-2">Type: {selectedPaper.paper_type}</p>}
                </section>
              )}

              {selectedPaper.main_effects && selectedPaper.main_effects.length > 0 && (
                <section>
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Main Effects ({selectedPaper.main_effects.length})</h3>
                  <div className="space-y-2">
                    {selectedPaper.main_effects.slice(0, 6).map((e, i) => (
                      <div key={i} className="p-3 border border-outline-variant rounded-lg bg-surface-container-lowest flex justify-between items-center group hover:border-secondary transition-all cursor-pointer shadow-sm">
                        <div>
                          <span className="text-xs font-bold text-on-surface">{e.from} → {e.to}</span>
                          {e.direction && <span className="ml-2 text-[10px] font-mono text-on-surface-variant">({e.direction})</span>}
                        </div>
                        <Link2 className="w-3.5 h-3.5 text-outline-variant group-hover:text-secondary transition-colors" />
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <div className="pt-4 border-t border-outline-variant">
                <button onClick={() => setCurrentView('graph')} className="w-full py-2.5 bg-primary-container text-on-primary-fixed rounded-lg text-sm font-semibold flex items-center justify-center gap-2 hover:opacity-90 transition-all shadow-md">
                  <FileText className="w-4 h-4" />
                  View in Graph
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <FileText className="w-10 h-10 text-outline mx-auto mb-3" />
              <p className="text-sm text-on-surface-variant">Select a paper from search results.</p>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}