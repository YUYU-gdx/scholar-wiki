import { Variable, GitBranch } from 'lucide-react';
import type { GraphNode, GraphEdge, PaperDetail, ModerationLink, InteractionLink } from '../../types';

interface RelatedEntitiesProps {
  paperId: string;
  libraryId: string;
  graphData: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    moderation_links?: ModerationLink[];
    interaction_links?: InteractionLink[];
    paper_map: Record<string, PaperDetail>;
  } | null;
  isOpen: boolean;
  onToggle: () => void;
}

type VariableCard = {
  variableName: string;
  definition: string;
  measurement: string;
  aliases: string[];
  relatedPapers: Array<{ paperId: string; title: string }>;
};

function cleanVarName(raw: string): string {
  const t = String(raw || '').trim();
  return t.replace(/^var::/i, '').trim();
}

function normVar(raw: string): string {
  return cleanVarName(raw).toLowerCase().replace(/\s+/g, ' ').trim();
}
function compactPreview(raw: string, n: number = 120): string {
  const t = String(raw || '').replace(/\s+/g, ' ').trim();
  if (t.length <= n) return t;
  return `${t.slice(0, n)}…`;
}

export function formatMeasurementMethods(methods: unknown): string {
  if (!Array.isArray(methods)) return '';
  return methods
    .map((item) => {
      if (typeof item === 'string') return item.trim();
      if (!item || typeof item !== 'object') return '';
      const row = item as Record<string, unknown>;
      const variable = String(row.variable || row.variable_name || '').trim();
      const operationalizedAs = Array.isArray(row.operationalized_as)
        ? row.operationalized_as.map((x) => String(x || '').trim()).filter(Boolean).join('、')
        : String(row.operationalized_as || row.measurement || row.measurement_text || '').trim();
      if (!operationalizedAs) return '';
      return variable ? `${variable}：${operationalizedAs}` : operationalizedAs;
    })
    .filter(Boolean)
    .join('；');
}

export default function RelatedEntities({ paperId, libraryId, graphData, isOpen, onToggle }: RelatedEntitiesProps) {
  if (!isOpen) return null;

  const paperEdges: GraphEdge[] = [];
  const paperModerations: ModerationLink[] = [];
  const paperInteractions: InteractionLink[] = [];
  const nodeById: Record<string, GraphNode> = {};
  const variableCards: VariableCard[] = [];

  const nodeLabel = (idOrName: string): string => {
    const t = String(idOrName || '').trim();
    const byId = nodeById[t];
    if (byId) return cleanVarName(String(byId.label || byId.name || byId.id || t));
    return cleanVarName(t);
  };

  if (graphData) {
    for (const n of graphData.nodes || []) nodeById[String(n.id || '')] = n;

    const scopedKey = `${libraryId}::${paperId}`;
    const paper = graphData.paper_map?.[scopedKey] || graphData.paper_map?.[paperId];
    const defs = Array.isArray((paper as any)?.variable_definitions) ? (paper as any).variable_definitions : [];
    const operationalization = ((paper as any)?.operationalization || {}) as Record<string, { operationalized_as?: unknown[] }>;

    const aliasToPapers = new Map<string, Array<{ paperId: string; title: string }>>();
    for (const [k, p] of Object.entries(graphData.paper_map || {})) {
      const pid = String((p as any)?.paper_id || k.split('::').at(-1) || '').trim();
      if (!pid) continue;
      const ptitle = String((p as any)?.display_title || (p as any)?.title || pid).trim();
      const pdefs = Array.isArray((p as any)?.variable_definitions) ? (p as any).variable_definitions : [];
      for (const d of pdefs) {
        const name = String((d as any)?.variable_name || (d as any)?.variable || '').trim();
        const aliases = Array.isArray((d as any)?.aliases) ? (d as any).aliases : [];
        const allNames = [name, ...aliases.map((x: any) => String(x || '').trim())].filter(Boolean);
        for (const nm of allNames) {
          const key = normVar(nm);
          if (!key) continue;
          const arr = aliasToPapers.get(key) || [];
          if (!arr.some((x) => x.paperId === pid)) arr.push({ paperId: pid, title: ptitle });
          aliasToPapers.set(key, arr);
        }
      }
    }

    const variableNames = new Set<string>();
    for (const d of defs) {
      const name = String((d as any)?.variable_name || (d as any)?.variable || '').trim();
      if (name) {
        variableNames.add(name);
        variableNames.add(`var::${name}`);
      }
      const aliases = Array.isArray((d as any)?.aliases) ? (d as any).aliases : [];
      const definition = String((d as any)?.definition || (d as any)?.definition_text || '').trim();
      const opFromPaper = operationalization[name]?.operationalized_as;
      const measurement = String((d as any)?.measurement || (d as any)?.measurement_text || '').trim()
        || formatMeasurementMethods((d as any)?.measurement_methods)
        || formatMeasurementMethods(opFromPaper);
      const aliasNames = [name, ...aliases.map((x: any) => String(x || '').trim())].filter(Boolean);
      const relatedMap = new Map<string, { paperId: string; title: string }>();
      for (const a of aliasNames) {
        const arr = aliasToPapers.get(normVar(a)) || [];
        for (const rp of arr) {
          if (rp.paperId === paperId) continue;
          relatedMap.set(rp.paperId, rp);
        }
      }
      variableCards.push({
        variableName: cleanVarName(name),
        definition,
        measurement,
        aliases: aliases.map((x: any) => cleanVarName(String(x || '').trim())).filter(Boolean),
        relatedPapers: Array.from(relatedMap.values()),
      });
    }

    for (const edge of graphData.edges || []) {
      const edgePid = String((edge as any).paper_id || (edge as any).paper_id_raw || '').trim();
      if (edgePid !== paperId) continue;
      const src = typeof edge.source === 'string' ? edge.source : (edge.source as any)?.id || '';
      const tgt = typeof edge.target === 'string' ? edge.target : (edge.target as any)?.id || '';
      if (variableNames.has(src) || variableNames.has(tgt) || src || tgt) {
        paperEdges.push(edge);
      }
    }

    for (const mod of graphData.moderation_links || []) {
      const pid = String((mod as any).paper_id || (mod as any).paper_id_raw || '').trim();
      if (pid === paperId) paperModerations.push(mod);
    }
    for (const inter of graphData.interaction_links || []) {
      const pid = String((inter as any).paper_id || (inter as any).paper_id_raw || '').trim();
      if (pid === paperId) paperInteractions.push(inter);
    }
  }

  const relationCount = paperEdges.length + paperModerations.length + paperInteractions.length;
  const jumpToText = (query: string) => {
    const q = String(query || '').replace(/\s+/g, ' ').trim();
    if (!q) return;
    window.dispatchEvent(new CustomEvent('reader-search-and-jump', { detail: { paperId, query: q } }));
  };
  const FoldField = ({
    label,
    text,
    clickable = false,
  }: {
    label: string;
    text: string;
    clickable?: boolean;
  }) => {
    const raw = String(text || '').trim();
    const has = !!raw;
    return (
      <details className="rounded-lg border border-outline-variant/70 bg-surface-container-lowest">
        <summary className="cursor-pointer list-none px-2 py-1.5 text-[13px] text-on-surface flex items-center justify-between">
          <span className="font-medium">{label}</span>
          <span className="text-outline">{has ? compactPreview(raw, 36) : '暂无'}</span>
        </summary>
        <div className="px-2 pb-2 text-xs text-on-surface-variant leading-relaxed">
          {has ? (
            clickable ? (
              <button className="underline decoration-dotted hover:text-on-surface text-left" onClick={() => jumpToText(raw)} title={raw}>
                {raw}
              </button>
            ) : (
              <span>{raw}</span>
            )
          ) : (
            <span>暂无</span>
          )}
        </div>
      </details>
    );
  };

  return (
    <div className="w-[360px] shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-4">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-on-surface">
            实体信息（变量 {variableCards.length}，关系 {relationCount}）
          </h4>
          <button className="text-xs text-outline hover:text-on-surface" onClick={onToggle}>×</button>
        </div>

        {variableCards.length === 0 && relationCount === 0 && (
          <p className="text-xs text-outline">暂无实体数据</p>
        )}

        <div className="mt-3">
          <div className="text-xs font-bold text-on-surface mb-2 tracking-wide">变量列表</div>
          <div className="space-y-3">
            {variableCards.map((v, i) => (
              <div key={`${v.variableName}-${i}`} className="rounded-xl border border-outline-variant p-3 bg-surface-container shadow-sm">
                <div className="flex items-center gap-1 text-sm font-semibold text-on-surface">
                  <Variable className="w-3 h-3 shrink-0" />
                  {v.variableName || '未命名变量'}
                </div>
                <div className="mt-2 text-xs text-on-surface-variant space-y-1.5">
                  <FoldField label="定义" text={v.definition} clickable />
                  <FoldField label="测量方法" text={v.measurement} clickable />
                  <FoldField label="别名" text={v.aliases.length ? v.aliases.join('、') : ''} />
                  <div className="mt-1">
                    <span className="text-outline">关联文献：</span>
                    {v.relatedPapers.length ? (
                      <div className="mt-0.5 space-y-0.5">
                        {v.relatedPapers.map((p) => (
                          <div key={`${v.variableName}-${p.paperId}`} className="truncate" title={p.paperId}>
                            {p.title}（{p.paperId}）
                          </div>
                        ))}
                      </div>
                    ) : '无'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4">
          <div className="text-xs font-bold text-on-surface mb-2 tracking-wide">关系列表</div>
          <div className="space-y-3">
            {paperEdges.map((edge, i) => {
              const src = nodeLabel(typeof edge.source === 'string' ? edge.source : (edge.source as any)?.id || '?');
              const tgt = nodeLabel(typeof edge.target === 'string' ? edge.target : (edge.target as any)?.id || '?');
              return (
                <div key={`edge-${i}`} className="rounded-xl border border-outline-variant p-3 bg-surface-container shadow-sm text-xs text-on-surface-variant space-y-1">
                  <div className="flex items-center gap-1 text-sm font-semibold text-on-surface"><GitBranch className="w-3 h-3 shrink-0" />主效应</div>
                  <FoldField label="起点变量" text={src} />
                  <FoldField label="终点变量" text={tgt} />
                  <FoldField label="方向/形式" text={String(edge.direction || edge.relation_form || '').trim()} />
                  <FoldField label="关系类型" text={String(edge.relation_type_std || '').trim()} />
                  <FoldField label="理论/假设" text={String(edge.hypothesis_label || '').trim()} />
                  <FoldField label="证据" text={String(edge.evidence_section || edge.evidence_snippet || '').trim()} clickable />
                  <FoldField label="验证" text={String(edge.verification || '').trim()} />
                </div>
              );
            })}
            {paperModerations.map((m, i) => {
              const mr = (m as any).moderated_relation || {};
              return (
                <div key={`mod-${i}`} className="rounded-xl border border-outline-variant p-3 bg-surface-container shadow-sm text-xs text-on-surface-variant space-y-1">
                  <div className="flex items-center gap-1 text-sm font-semibold text-on-surface"><GitBranch className="w-3 h-3 shrink-0" />调节效应</div>
                  <FoldField label="调节变量" text={nodeLabel(String((m as any).moderator_var || (m as any).moderator_node_id || ''))} />
                  <FoldField label="被调节关系" text={`${nodeLabel(String(mr.source || ''))} → ${nodeLabel(String(mr.target || ''))}`} />
                  <FoldField label="方向/形式" text={String((m as any).direction || '').trim()} />
                  <FoldField label="理论/假设" text={String((m as any).hypothesis_label || '').trim()} />
                  <FoldField label="证据" text={String((m as any).evidence_section || (m as any).evidence_snippet || '').trim()} clickable />
                  <FoldField label="验证" text={String((m as any).verification || '').trim()} />
                </div>
              );
            })}
            {paperInteractions.map((it, i) => (
              <div key={`int-${i}`} className="rounded-xl border border-outline-variant p-3 bg-surface-container shadow-sm text-xs text-on-surface-variant space-y-1">
                <div className="flex items-center gap-1 text-sm font-semibold text-on-surface"><GitBranch className="w-3 h-3 shrink-0" />交互效应</div>
                <FoldField label="输入变量" text={((it as any).inputs || []).map((x: string) => nodeLabel(x)).join('、')} />
                <FoldField label="输出变量" text={nodeLabel(String((it as any).output || (it as any).output_node_id || ''))} />
                <FoldField label="交互类型" text={String((it as any).interaction_type || '').trim()} />
                <FoldField label="调节变量" text={nodeLabel(String((it as any).moderator || (it as any).moderator_node_id || ''))} />
                <FoldField label="效应形式" text={String((it as any).effect || '').trim()} />
                <FoldField label="理论/假设" text={String((it as any).hypothesis_label || '').trim()} />
                <FoldField label="证据" text={String((it as any).evidence_section || (it as any).evidence_snippet || '').trim()} clickable />
                <FoldField label="验证" text={String((it as any).verification || '').trim()} />
                <FoldField label="描述" text={String((it as any).description || '').trim()} />
              </div>
            ))}
            {relationCount === 0 && (
              <p className="text-xs text-outline">暂无关系数据</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
