export type TimelineRow = {
  title: string;
  detail: string;
  state: 'running' | 'completed' | 'failed' | 'info';
  kind: 'delta_text' | 'event';
};

function stringifyToolPayload(payload: unknown): string {
  if (payload == null) return '';
  if (typeof payload === 'string') return payload;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function renderScalar(value: unknown): string {
  if (value === null || value === undefined) return '(empty)';
  if (typeof value === 'string') return value || '(empty)';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return stringifyToolPayload(value);
}

function extractToolName(toolCall: Record<string, unknown>): string {
  const raw = String(toolCall.name || toolCall.tool || toolCall.summary || toolCall.kind || 'tool').trim();
  const normalized = raw.split('.').pop() || raw;
  const key = normalized.toLowerCase();
  if (key.includes('rag_search') || key.includes('rag')) return 'RAG';
  if (key.includes('grep') || key.includes('rg')) return 'Local File Search';
  if (key.includes('graph_search')) return 'Graph Search';
  if (key.includes('literature_search')) return 'Literature Search';
  if (key.includes('literature_fetch_object')) return 'Fetch Object';
  return normalized || 'tool';
}

function normalizeToolArgs(args: unknown): Array<{ label: string; value: string }> {
  if (!isPlainObject(args)) return [{ label: '参数', value: renderScalar(args) }];
  const q = args.query ?? args.search_query ?? args.keyword ?? args.text ?? args.pattern;
  const topK = args.top_k ?? args.k ?? args.limit;
  const rows: Array<{ label: string; value: string }> = [];
  rows.push({ label: '工具名称', value: renderScalar(args.tool ?? args.name ?? args.type ?? '') });
  if (q !== undefined) rows.push({ label: '检索字符串', value: renderScalar(q) });
  if (topK !== undefined) rows.push({ label: '返回条数', value: renderScalar(topK) });
  Object.entries(args).forEach(([k, v]) => {
    if (['tool', 'name', 'type', 'query', 'search_query', 'keyword', 'text', 'pattern', 'top_k', 'k', 'limit'].includes(k)) return;
    rows.push({ label: k, value: renderScalar(v) });
  });
  return rows;
}

function normalizeToolResult(result: unknown): string[] {
  if (!isPlainObject(result)) return [renderScalar(result)];
  const structured = isPlainObject(result.structuredContent) ? (result.structuredContent as Record<string, unknown>) : result;
  const candidates = [structured.paragraph_hits, structured.hits, structured.results, structured.merged_hits];
  for (const c of candidates) {
    if (!Array.isArray(c)) continue;
    const lines = c.slice(0, 8).map((item, idx) => {
      const row = isPlainObject(item) ? item : {};
      const title = String(row.title || row.paper_title || row.name || row.id || `结果${idx + 1}`);
      const pid = String(row.paper_id || row.paperId || '').trim();
      return `[${idx + 1}] ${title}${pid ? `（${pid}）` : ''}`;
    });
    if (lines.length > 0) return lines;
  }
  return [stringifyToolPayload(result)];
}

function extractToolArgs(toolCall: Record<string, unknown>): unknown {
  return toolCall.arguments ?? toolCall.args ?? (toolCall.raw && typeof toolCall.raw === 'object' ? (toolCall.raw as Record<string, unknown>).arguments : undefined);
}

function extractToolResult(toolCall: Record<string, unknown>): unknown {
  if (toolCall.result !== undefined) return toolCall.result;
  if (toolCall.output !== undefined) return toolCall.output;
  if (toolCall.raw && typeof toolCall.raw === 'object') {
    const raw = toolCall.raw as Record<string, unknown>;
    if (raw.result !== undefined) return raw.result;
    if (raw.output !== undefined) return raw.output;
  }
  return undefined;
}

export function toTimelineRow(raw: unknown): TimelineRow | null {
  const row = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const evt = String(row.event || '').trim().toLowerCase();
  const summary = String(row.summary || row.tool || row.item || row.stage || '').trim();
  const stateRaw = String(row.state || row.status || '').trim().toLowerCase();
  const state: TimelineRow['state'] =
    stateRaw === 'failed' || stateRaw === 'error'
      ? 'failed'
      : stateRaw === 'completed' || stateRaw === 'ok' || stateRaw === 'success'
        ? 'completed'
        : stateRaw === 'started' || stateRaw === 'running' || stateRaw === 'streaming'
          ? 'running'
          : 'info';

  if (evt === 'tool_call') {
    const toolName = extractToolName(row);
    const detail = stringifyToolPayload({
      参数: normalizeToolArgs(extractToolArgs(row)),
      结果: normalizeToolResult(extractToolResult(row)),
    });
    return { title: `工具调用：${toolName}`, detail, state, kind: 'event' };
  }
  if (evt === 'agent_item_started' || evt === 'agent_item_completed') {
    const item = String(row.item || row.kind || '步骤').trim();
    const title = `${evt.endsWith('started') ? '步骤开始' : '步骤完成'}：${item || 'unknown'}`;
    return { title, detail: stringifyToolPayload(row.detail || row), state, kind: 'event' };
  }
  if (evt === 'agent_item_delta') {
    const text = String(row.text || row.summary || '').trim();
    return { title: '模型增量输出', detail: text || '(empty)', state: 'running', kind: 'delta_text' };
  }
  if (evt === 'status') {
    const stage = String(row.stage || '').trim();
    const label = String(row.label || '').trim();
    return { title: `状态：${stage || 'unknown'}`, detail: label || stringifyToolPayload(row), state, kind: 'event' };
  }
  if (evt === 'citation') {
    return { title: '检索事件', detail: stringifyToolPayload(row), state: 'info', kind: 'event' };
  }
  if (evt === 'started' || evt === 'completed' || evt === 'failed') {
    return null;
  }
  if (summary || Object.keys(row).length > 0) {
    return { title: summary || '事件', detail: stringifyToolPayload(row), state, kind: 'event' };
  }
  return null;
}
