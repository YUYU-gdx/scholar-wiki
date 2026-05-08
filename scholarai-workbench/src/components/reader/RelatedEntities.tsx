import { Variable, GitBranch } from 'lucide-react';
import type { GraphNode, GraphEdge, PaperDetail } from '../../types';

interface RelatedEntitiesProps {
  paperId: string;
  libraryId: string;
  graphData: { nodes: GraphNode[]; edges: GraphEdge[]; paper_map: Record<string, PaperDetail> } | null;
  isOpen: boolean;
  onToggle: () => void;
}

export default function RelatedEntities({ paperId, libraryId, graphData, isOpen, onToggle }: RelatedEntitiesProps) {
  if (!isOpen) return null;

  const paperNodes: GraphNode[] = [];
  const paperEdges: GraphEdge[] = [];

  if (graphData) {
    const scopedKey = `${libraryId}::${paperId}`;
    const paper = graphData.paper_map?.[scopedKey] || graphData.paper_map?.[paperId];
    const variableNames = new Set<string>(
      (paper?.context_variables || []).concat(
        (paper?.main_effects || []).flatMap((e: any) => [e.from, e.to])
      )
    );

    for (const node of graphData.nodes) {
      if (node.type === 'variable' && variableNames.has(node.id)) {
        paperNodes.push(node);
      }
    }

    for (const edge of graphData.edges) {
      const src = typeof edge.source === 'string' ? edge.source : (edge.source as any)?.id || '';
      const tgt = typeof edge.target === 'string' ? edge.target : (edge.target as any)?.id || '';
      if (variableNames.has(src) && variableNames.has(tgt)) {
        paperEdges.push(edge);
      }
    }
  }

  return (
    <div className="w-60 shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-on-surface-variant">
            Related ({paperNodes.length} variables, {paperEdges.length} effects)
          </h4>
          <button className="text-xs text-outline hover:text-on-surface" onClick={onToggle}>×</button>
        </div>

        {paperNodes.length === 0 && paperEdges.length === 0 && (
          <p className="text-xs text-outline">No extracted entities</p>
        )}

        {paperNodes.map(node => (
          <button
            key={node.id}
            className="flex items-center gap-1 w-full text-left text-xs px-1.5 py-0.5 rounded truncate hover:bg-surface-container-low text-on-surface-variant"
            onClick={() => window.dispatchEvent(new CustomEvent('navigate-to-node', { detail: { nodeId: node.id } }))}
          >
            <Variable className="w-3 h-3 shrink-0" />
            {node.label || node.name || node.id}
          </button>
        ))}

        {paperEdges.map((edge, i) => {
          const src = typeof edge.source === 'string' ? edge.source : (edge.source as any)?.id || '?';
          const tgt = typeof edge.target === 'string' ? edge.target : (edge.target as any)?.id || '?';
          return (
            <div key={i} className="flex items-center gap-1 text-[10px] text-on-surface-variant px-1.5 py-0.5 truncate">
              <GitBranch className="w-3 h-3 shrink-0" />
              {src} → {tgt}
            </div>
          );
        })}
      </div>
    </div>
  );
}
