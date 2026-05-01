import { useState, useEffect } from 'react';
import { FileText, BookOpen, Share2 } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { PaperDetail, VariableDetail } from '../types';

export default function ReaderView() {
  const {
    selectedPaperId,
    selectedPaperLibraryId,
    setSelectedPaperId,
    selectedNodeId,
    selectedNodeLibraryId,
    setSelectedNodeId,
    setCurrentView,
  } = useApp();
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [variable, setVariable] = useState<VariableDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedPaperId) return;
    setLoading(true);
    setError(null);
    api.graph.paper(selectedPaperId, selectedPaperLibraryId).then(setPaper).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [selectedPaperId, selectedPaperLibraryId]);

  useEffect(() => {
    if (!selectedNodeId) return;
    api.graph.variable(selectedNodeId, selectedNodeLibraryId).then(setVariable).catch(() => setVariable(null));
  }, [selectedNodeId, selectedNodeLibraryId]);

  if (!selectedPaperId && !selectedNodeId) {
    return <div className="flex-1 flex items-center justify-center"><div className="text-center space-y-4"><BookOpen className="w-12 h-12 text-outline mx-auto" /><h3 className="text-lg font-medium text-on-surface">Paper & Variable Reader</h3></div></div>;
  }

  return (
    <div className="flex-1 overflow-y-auto p-8 bg-surface-container-low">
      {loading && <div className="text-sm text-on-surface-variant">Loading...</div>}
      {error && <div className="text-sm text-error">{error}</div>}

      {paper && !loading && (
        <div className="max-w-[800px] mx-auto space-y-6">
          <div>
            <span className="bg-secondary-container/30 text-secondary px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-widest border border-secondary/20">Paper</span>
            <h2 className="text-2xl font-medium text-on-surface tracking-tight mt-2">{paper.display_title || paper.title || paper.paper_id}</h2>
            <p className="text-sm text-on-surface-variant mt-2">{paper.paper_id}</p>
          </div>
          {paper.variable_definitions && paper.variable_definitions.length > 0 && (
            <section>
              <h3 className="text-xs font-mono uppercase text-outline tracking-wider mb-3">Variable Definitions</h3>
              <div className="space-y-2">
                {paper.variable_definitions.map((vd, i) => (
                  <div key={i} className="p-3 bg-surface-container-low border border-outline-variant rounded-xl">
                    <div className="text-sm font-bold text-on-surface">{vd.variable}</div>
                    {vd.definition && <p className="text-xs text-on-surface-variant mt-1">{vd.definition}</p>}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      {variable && !loading && !paper && (
        <div className="max-w-[800px] mx-auto space-y-6">
          <div>
            <span className="bg-secondary-container/30 text-secondary px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-widest border border-secondary/20">Variable</span>
            <h2 className="text-2xl font-medium text-on-surface tracking-tight mt-2">{variable.node?.label || variable.node?.name || variable.node?.id || ''}</h2>
          </div>
          <div className="space-y-2">
            {(variable.paper_groups || []).map((pg, i) => (
              <div key={i} className="p-4 bg-surface-container-lowest border border-outline-variant rounded-xl">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2"><FileText className="w-4 h-4 text-secondary" /><span className="text-sm font-semibold text-on-surface">{pg.paper_id}</span></div>
                  {pg.open_online_url && <a href={pg.open_online_url} target="_blank" rel="noopener noreferrer" className="text-secondary text-xs hover:underline">Open</a>}
                </div>
              </div>
            ))}
          </div>
          <button onClick={() => setCurrentView('graph')} className="flex items-center gap-2 px-3 py-1.5 bg-primary-container text-secondary rounded-lg text-[11px] font-mono font-bold uppercase tracking-wider"><Share2 className="w-3.5 h-3.5" />View in Graph</button>
        </div>
      )}

      <div className="mt-8">
        <button onClick={() => { setPaper(null); setVariable(null); setSelectedPaperId(null); setSelectedNodeId(null); }} className="text-xs px-3 py-1.5 border border-outline-variant rounded-lg text-on-surface-variant">Clear</button>
      </div>
    </div>
  );
}
