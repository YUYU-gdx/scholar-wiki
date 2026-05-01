import { useState, useEffect } from 'react';
import { FileText, ChevronRight, Link2, Verified, BookOpen, Share2 } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { PaperDetail, VariableDetail } from '../types';

export default function ReaderView() {
  const { selectedPaperId, setSelectedPaperId, selectedNodeId, setSelectedNodeId, setCurrentView } = useApp();
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [variable, setVariable] = useState<VariableDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (selectedPaperId) {
      setLoading(true);
      setError(null);
      api.graph.paper(selectedPaperId).then(setPaper).catch(e => setError(e.message)).finally(() => setLoading(false));
    }
  }, [selectedPaperId]);

  useEffect(() => {
    if (selectedNodeId) {
      api.graph.variable(selectedNodeId).then(setVariable).catch(() => setVariable(null));
    }
  }, [selectedNodeId]);

  if (!selectedPaperId && !selectedNodeId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-4">
          <BookOpen className="w-12 h-12 text-outline mx-auto" />
          <h3 className="text-lg font-medium text-on-surface">Paper & Variable Reader</h3>
          <p className="text-sm text-on-surface-variant">Select a paper from the Library or a variable from the Graph to view details.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex overflow-hidden bg-surface-container-low">
      <section className="flex-1 flex flex-col relative overflow-hidden">
        <div className="h-12 bg-surface-container-lowest border-b border-outline-variant px-6 flex items-center justify-between z-30 precision-shadow">
          <div className="flex items-center gap-4">
            <span className="text-[11px] font-mono font-bold text-outline uppercase tracking-tight">
              {paper ? paper.doi || paper.paper_id : variable ? variable.node?.id : ''}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setPaper(null); setVariable(null); setSelectedPaperId(null); setSelectedNodeId(null); }}
              className="flex items-center gap-2 px-3 py-1.5 border border-outline-variant rounded-lg text-[11px] font-mono font-bold uppercase tracking-wider text-on-surface-variant hover:border-secondary hover:text-secondary transition-all active:scale-95"
            >
              Clear
            </button>
            {variable && (
              <button
                onClick={() => setCurrentView('graph')}
                className="flex items-center gap-2 px-3 py-1.5 bg-primary-container text-secondary rounded-lg text-[11px] font-mono font-bold uppercase tracking-wider hover:opacity-90 transition-all shadow-md active:scale-95"
              >
                <Share2 className="w-3.5 h-3.5" />
                View in Graph
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {loading && (
            <div className="flex items-center justify-center h-64">
              <div className="w-6 h-6 border-2 border-secondary border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {error && (
            <div className="text-center py-16">
              <p className="text-error text-sm">{error}</p>
            </div>
          )}

          {paper && !loading && (
            <div className="max-w-[800px] mx-auto space-y-8">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="bg-secondary-container/30 text-secondary px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-widest border border-secondary/20">Paper</span>
                  {paper.extractability_status && (
                    <span className="bg-surface-container text-on-surface-variant px-2 py-0.5 rounded text-[10px] font-mono uppercase">{paper.extractability_status}</span>
                  )}
                </div>
                <h2 className="text-2xl font-medium text-on-surface tracking-tight font-sans">{paper.title || paper.paper_id}</h2>
                <p className="text-sm text-on-surface-variant mt-2">
                  {paper.publication_year && <span>Year: {paper.publication_year}</span>}
                  {paper.doi && <span className="ml-4">DOI: {paper.doi}</span>}
                  {paper.paper_citation_count != null && <span className="ml-4">Citations: {paper.paper_citation_count}</span>}
                </p>
              </div>

              {paper.paper_domains && paper.paper_domains.length > 0 && (
                <section>
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Domains</h3>
                  <div className="flex flex-wrap gap-2">
                    {paper.paper_domains.map((d, i) => (
                      <span key={i} className="px-2.5 py-1.5 bg-surface-container text-on-surface-variant text-[10px] font-mono uppercase rounded border border-outline-variant/30">{d}</span>
                    ))}
                  </div>
                </section>
              )}

              {paper.main_effects && paper.main_effects.length > 0 && (
                <section>
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Main Effects</h3>
                  <div className="space-y-2">
                    {paper.main_effects.map((e, i) => (
                      <div key={i} className="p-3 bg-surface-container-low border-l-2 border-secondary rounded-r-xl">
                        <div className="flex items-center gap-2 text-xs font-mono">
                          <span className="text-on-surface font-bold">{e.from}</span>
                          <span className="text-secondary">→</span>
                          <span className="text-on-surface font-bold">{e.to}</span>
                          {e.direction && <span className="text-outline ml-2">{e.direction}</span>}
                          {e.verification && <span className="bg-secondary-container/20 text-secondary px-1.5 py-0.5 rounded text-[9px]">{e.verification}</span>}
                        </div>
                        {e.description && <p className="text-xs text-on-surface-variant mt-1">{e.description}</p>}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {paper.moderations && paper.moderations.length > 0 && (
                <section>
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Moderations</h3>
                  <div className="space-y-2">
                    {paper.moderations.map((m, i) => (
                      <div key={i} className="p-3 bg-surface-container-low border-l-2 border-violet-400 rounded-r-xl">
                        <span className="text-xs font-mono text-on-surface">Moderator: <strong>{m.moderator_var}</strong></span>
                        <span className="text-outline ml-2">{m.direction || ''}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {paper.variable_definitions && paper.variable_definitions.length > 0 && (
                <section>
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Variable Definitions</h3>
                  <div className="space-y-2">
                    {paper.variable_definitions.map((vd, i) => (
                      <div key={i} className="p-3 bg-surface-container-low border border-outline-variant rounded-xl">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-bold text-on-surface">{vd.variable}</span>
                          {vd.aliases && vd.aliases.length > 0 && (
                            <span className="text-[10px] text-outline font-mono">aliases: {vd.aliases.join(', ')}</span>
                          )}
                        </div>
                        {vd.definition && <p className="text-xs text-on-surface-variant">{vd.definition}</p>}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}

          {variable && !loading && !paper && (
            <div className="max-w-[800px] mx-auto space-y-8">
              <div>
                <span className="bg-secondary-container/30 text-secondary px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-widest border border-secondary/20">Variable</span>
                <h2 className="text-2xl font-medium text-on-surface tracking-tight font-sans mt-2">{variable.node?.label || variable.node?.name || variable.node?.id || ''}</h2>
                <div className="grid grid-cols-3 gap-3 mt-4">
                  <div className="p-3 border border-outline-variant/16 rounded-xl bg-surface-container/10">
                    <span className="text-[10px] text-outline block">Total Papers</span>
                    <strong className="text-sm text-on-surface">{variable.paper_count_total}</strong>
                  </div>
                  <div className="p-3 border border-outline-variant/16 rounded-xl bg-surface-container/10">
                    <span className="text-[10px] text-outline block">Edge Papers</span>
                    <strong className="text-sm text-on-surface">{variable.paper_count_edge}</strong>
                  </div>
                  <div className="p-3 border border-outline-variant/16 rounded-xl bg-surface-container/10">
                    <span className="text-[10px] text-outline block">Moderation</span>
                    <strong className="text-sm text-on-surface">{variable.paper_count_moderation}</strong>
                  </div>
                </div>
              </div>

              {variable.paper_groups && variable.paper_groups.length > 0 && (
                <section>
                  <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Paper Groups</h3>
                  <div className="space-y-3">
                    {variable.paper_groups.map((pg, i) => (
                      <div key={i} className="p-4 bg-surface-container-lowest border border-outline-variant rounded-xl">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <FileText className="w-4 h-4 text-secondary" />
                            <span className="text-sm font-semibold text-on-surface">{pg.paper_id}</span>
                            {pg.publication_year && <span className="text-[10px] text-outline font-mono">{pg.publication_year}</span>}
                          </div>
                          {pg.open_online_url && (
                            <a href={pg.open_online_url} target="_blank" rel="noopener noreferrer" className="text-secondary text-xs hover:underline">
                              Open
                            </a>
                          )}
                        </div>
                        {pg.concepts && pg.concepts.length > 0 && (
                          <div className="flex flex-wrap gap-1 mb-2">
                            {pg.concepts.map((c, ci) => (
                              <span key={ci} className="px-1.5 py-0.5 bg-secondary-container/20 text-secondary text-[9px] font-mono rounded">{c}</span>
                            ))}
                          </div>
                        )}
                        {pg.relations && pg.relations.length > 0 && (
                          <div className="space-y-1">
                            {pg.relations.slice(0, 5).map((r, ri) => (
                              <div key={ri} className="text-[11px] font-mono text-on-surface-variant">
                                <span className="text-secondary font-bold">{r.type}</span>
                                {r.source && <span> {r.source} → {r.target}</span>}
                                {r.direction && <span className="ml-1 text-outline">({r.direction})</span>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}