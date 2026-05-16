import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { PlusSquare, Bot, Send, Activity, Clock, Trash2, X, ChevronDown, Zap } from 'lucide-react';
import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import { useApp } from '../app-context';
import { api } from '../api';
import type { ChatSession, ChatMessage, Citation as CitationType } from '../types';

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
  if (value === null || value === undefined) return '（空）';
  if (typeof value === 'string') return value || '（空）';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return stringifyToolPayload(value);
}

function normalizeCitationText(c: CitationType): { sentence: string; paragraph: string } {
  const ctx = isPlainObject(c.context) ? c.context : {};
  const paragraphCtx = isPlainObject(ctx.paragraph) ? ctx.paragraph : {};
  const sentenceCtx = isPlainObject(ctx.sentence) ? ctx.sentence : {};
  const sentence = String(c.sentence || sentenceCtx.text || c.text || '').trim();
  const paragraph = String(c.paragraph || paragraphCtx.text || c.text || '').trim();
  return { sentence, paragraph };
}

function ensureCitationMarkers(answer: string, citations: CitationType[]): string {
  const text = String(answer || '');
  if (!citations.length) return text;
  if (/\[\d+\]/.test(text)) return text;
  const refs = citations.map((_, idx) => `[${idx + 1}]`).join('');
  return `${text}\n\n${refs}`;
}

function extractToolName(toolCall: Record<string, unknown>): string {
  const raw = String(
    toolCall.name ||
    toolCall.tool ||
    toolCall.summary ||
    toolCall.kind ||
    'tool',
  ).trim();
  const normalized = raw.split('.').pop() || raw;
  const key = normalized.toLowerCase();
  if (key.includes('rag_search') || key.includes('rag')) return 'RAG';
  if (key.includes('grep') || key.includes('rg')) return '本地文件搜索';
  if (key.includes('graph_search')) return '图谱检索';
  if (key.includes('literature_search')) return '文献检索';
  if (key.includes('literature_fetch_object')) return '对象读取';
  return normalized || 'tool';
}

function toolNameZh(toolName: string): string {
  const key = String(toolName || '').toLowerCase();
  if (key.includes('rag')) return 'RAG';
  if (key.includes('local file search') || key.includes('grep')) return '本地文件搜索';
  if (key.includes('graph search')) return '图谱检索';
  if (key.includes('literature search')) return '文献检索';
  if (key.includes('fetch object')) return '对象读取';
  return toolName || '未知工具';
}

function normalizeToolArgs(args: unknown): Array<{ label: string; value: string }> {
  if (!isPlainObject(args)) return [{ label: '参数', value: renderScalar(args) }];
  const q = args.query ?? args.search_query ?? args.keyword ?? args.text ?? args.pattern;
  const topK = args.top_k ?? args.k ?? args.limit;
  const rows: Array<{ label: string; value: string }> = [];
  rows.push({ label: '工具名称', value: renderScalar(args.tool ?? args.name ?? args.type ?? '') });
  if (q !== undefined) rows.push({ label: '检索字符串', value: renderScalar(q) });
  if (topK !== undefined) rows.push({ label: '返回条数', value: renderScalar(topK) });
  const labelMap: Record<string, string> = {
    library_id: '文献库',
    workspace_path: '工作区路径',
    file_path: '文件路径',
    paper_id: '文献ID',
    section_id: '章节ID',
    sentence_id: '句子ID',
    route: '检索路由',
    query_rewritten: '重写查询',
    keyword_weight: '关键词权重',
    rag_weight: 'RAG 权重',
  };
  Object.entries(args).forEach(([k, v]) => {
    if (['tool', 'name', 'type', 'query', 'search_query', 'keyword', 'text', 'pattern', 'top_k', 'k', 'limit'].includes(k)) return;
    rows.push({ label: labelMap[k] || k, value: renderScalar(v) });
  });
  return rows;
}

function normalizeToolResult(result: unknown): string[] {
  if (!isPlainObject(result)) return [renderScalar(result)];
  const structured = isPlainObject(result.structuredContent) ? result.structuredContent as Record<string, unknown> : result;
  const candidates = [
    structured.paragraph_hits,
    structured.hits,
    structured.results,
    structured.merged_hits,
  ];
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

type TimelineRow = {
  title: string;
  detail: string;
  state: 'running' | 'completed' | 'failed' | 'info';
  kind: 'delta_text' | 'event';
};

function toTimelineRow(raw: unknown): TimelineRow | null {
  const row = (raw && typeof raw === 'object') ? (raw as Record<string, unknown>) : {};
  const evt = String(row.event || '').trim().toLowerCase();
  const summary = String(row.summary || row.tool || row.item || row.stage || '').trim();
  const stateRaw = String(row.state || row.status || '').trim().toLowerCase();
  const state: TimelineRow['state'] =
    stateRaw === 'failed' || stateRaw === 'error' ? 'failed'
      : stateRaw === 'completed' || stateRaw === 'ok' || stateRaw === 'success' ? 'completed'
        : stateRaw === 'started' || stateRaw === 'running' || stateRaw === 'streaming' ? 'running'
          : 'info';

  if (evt === 'tool_call') {
    const toolName = toolNameZh(extractToolName(row));
    const detail = stringifyToolPayload({
      参数: normalizeToolArgs(extractToolArgs(row)),
      结果: normalizeToolResult(extractToolResult(row)),
    });
    return { title: `工具调用：${toolName}`, detail, state, kind: 'event' };
  }
  if (evt === 'agent_item_started' || evt === 'agent_item_completed') {
    const item = String(row.item || row.kind || '步骤').trim();
    const title = `${evt.endsWith('started') ? '步骤开始' : '步骤完成'}：${item || '未知'}`;
    return { title, detail: stringifyToolPayload(row.detail || row), state, kind: 'event' };
  }
  if (evt === 'agent_item_delta') {
    const text = String(row.text || row.summary || '').trim();
    return { title: '模型增量输出', detail: text || '（空）', state: 'running', kind: 'delta_text' };
  }
  if (evt === 'agent_item_thinking') {
    const detail = String(row.detail || row.summary || '').trim();
    return { title: '思考过程', detail: detail || '（空）', state: 'running', kind: 'event' };
  }
  if (evt === 'status') {
    const stage = String(row.stage || '').trim();
    const label = String(row.label || '').trim();
    return { title: `状态：${stage || '未知'}`, detail: label || stringifyToolPayload(row), state, kind: 'event' };
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


export default function ChatView() {
  const {
    sessions,
    setSessions,
    activeSessionId,
    setActiveSessionId,
    activeLibraryId,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setCurrentView,
  } = useApp();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<'fast' | 'agent'>('agent');
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('codex-local');
  const [submitting, setSubmitting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [showModeSwitcher, setShowModeSwitcher] = useState(false);
  const [citationModal, setCitationModal] = useState<CitationType | null>(null);
  const [expandedToolItems, setExpandedToolItems] = useState<Record<string, boolean>>({});
  const streamRef = useRef<EventSource | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const md = useMemo(() => new MarkdownIt({ html: false, linkify: true, breaks: true }), []);
  const renderMarkdown = useCallback((text: string) => ({ __html: DOMPurify.sanitize(md.render(String(text || ''))) }), [md]);

  const activeSession = sessions.find(s => s.session_id === activeSessionId);
  const openCitationInReader = useCallback((c: CitationType) => {
    const paperId = String(c.paper_id || '').trim();
    if (!paperId) {
      setCitationModal(c);
      return;
    }
    setSelectedPaperId(paperId);
    setSelectedPaperLibraryId(activeLibraryId);
    setCurrentView('reader');
  }, [activeLibraryId, setCurrentView, setSelectedPaperId, setSelectedPaperLibraryId]);

  const refreshSessions = useCallback(async () => {
    try {
      const res = await api.chat.listSessions();
      setSessions(res.sessions || []);
    } catch { /* ignore */ }
  }, [setSessions]);

  useEffect(() => { refreshSessions(); }, [refreshSessions]);

  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.close();
        streamRef.current = null;
      }
    };
  }, [activeSessionId]);

  const loadSession = useCallback(async (sessionId: string) => {
    setLoadingSession(true);
    try {
      const res = await api.chat.getSession(sessionId);
      const incoming = Array.isArray(res.messages) ? res.messages : [];
      const normalized: ChatMessage[] = [];
      incoming.forEach((msg) => {
        const m = { ...msg, tool_trace: Array.isArray(msg.tool_trace) ? msg.tool_trace : [] } as ChatMessage;
        const last = normalized.length > 0 ? normalized[normalized.length - 1] : null;
        if (m.role === 'assistant' && last && last.role === 'assistant') {
          normalized[normalized.length - 1] = {
            ...last,
            content: [String(last.content || '').trim(), String(m.content || '').trim()].filter(Boolean).join('\n'),
            citations: [...(Array.isArray(last.citations) ? last.citations : []), ...(Array.isArray(m.citations) ? m.citations : [])],
            tool_trace: [...(Array.isArray(last.tool_trace) ? last.tool_trace : []), ...(Array.isArray(m.tool_trace) ? m.tool_trace : [])],
            status: m.status || last.status,
            error_detail: m.error_detail || last.error_detail,
          };
          return;
        }
        normalized.push(m);
      });
      setMessages(normalized);
      setActiveSessionId(sessionId);
      if (res.session?.default_mode) setMode(res.session.default_mode as 'fast' | 'agent');
    } catch { setMessages([]); }
    finally { setLoadingSession(false); }
  }, [setActiveSessionId]);

  const createSession = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const session = await api.chat.createSession('新会话', activeLibraryId, mode);
      setSessions(prev => [session, ...prev]);
      setActiveSessionId(session.session_id);
      setMessages([]);
    } catch { /* ignore */ }
    finally { setCreating(false); }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      await api.chat.deleteSession(sessionId);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
    } catch { /* ignore */ }
  };

  const attachStream = useCallback((sessionId: string, messageId: string) => {
    if (streamRef.current) { streamRef.current.close(); }
    const es = api.chat.streamEvents(sessionId, messageId);

    es.addEventListener('delta', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages(prev => prev.map(m =>
          m.message_id === messageId
            ? { ...m, content: (m.content || '') + (payload.text || ''), status: 'running' as const }
            : m
        ));
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('tool_call', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages(prev => prev.map(m =>
          m.message_id === messageId
            ? { ...m, tool_trace: [...(m.tool_trace || []), { ...payload, event: 'tool_call' }], status: 'running' as const }
            : m
        ));
      } catch { /* ignore */ }
    });

    const pushEvent = (evtName: string, evt: Event) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data || '{}');
        setMessages(prev => prev.map(m =>
          m.message_id === messageId
            ? { ...m, tool_trace: [...(m.tool_trace || []), { ...payload, event: evtName }], status: 'running' as const }
            : m
        ));
      } catch { /* ignore */ }
    };
    es.addEventListener('agent_item_started', (evt) => pushEvent('agent_item_started', evt));
    es.addEventListener('agent_item_completed', (evt) => pushEvent('agent_item_completed', evt));
    es.addEventListener('agent_item_delta', (evt) => pushEvent('agent_item_delta', evt));
    es.addEventListener('status', (evt) => pushEvent('status', evt));
    es.addEventListener('citation', (evt) => pushEvent('citation', evt));

    es.addEventListener('completed', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages(prev => prev.map(m =>
          m.message_id === messageId
            ? {
                ...m,
                content: payload.answer || m.content || '',
                citations: Array.isArray(payload.citations) && payload.citations.length > 0 ? payload.citations : (m.citations || []),
                retrieval: (payload.retrieval_trace && typeof payload.retrieval_trace === 'object') ? payload.retrieval_trace : (m.retrieval || {}),
                tool_trace: (m.tool_trace && m.tool_trace.length > 0)
                  ? m.tool_trace
                  : (Array.isArray(payload.tool_trace) ? payload.tool_trace : []),
                status: 'completed' as const,
              }
            : m
        ));
      } catch { /* ignore */ }
      es.close();
      streamRef.current = null;
      refreshSessions();
    });

    es.addEventListener('failed', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages(prev => prev.map(m =>
          m.message_id === messageId
            ? { ...m, status: 'failed' as const, error_detail: payload.error || 'failed' }
            : m
        ));
      } catch { /* ignore */ }
      es.close();
      streamRef.current = null;
    });

    streamRef.current = es;
  }, [refreshSessions]);

  const sendMessage = async () => {
    if (!activeSessionId || !input.trim() || submitting) return;
    const content = input.trim();
    setInput('');
    setSubmitting(true);
    try {
      const res = await api.chat.sendMessage(activeSessionId, content, activeLibraryId, mode, provider, model);
      const userMsg: ChatMessage = {
        message_id: res.user_message_id,
        session_id: activeSessionId,
        role: 'user',
        content,
        status: 'completed',
        citations: [],
        tool_trace: [],
      };
      const assistantMsg: ChatMessage = {
        message_id: res.assistant_message_id,
        session_id: activeSessionId,
        role: 'assistant',
        content: '',
        status: 'running',
        citations: [],
        tool_trace: [],
      };
      setMessages(prev => [...prev, userMsg, assistantMsg]);
      if (res.stream_url) {
        attachStream(activeSessionId, res.assistant_message_id);
      }
    } catch {
      setMessages(prev => [...prev, {
        message_id: `err_${Date.now()}`,
        session_id: activeSessionId,
        role: 'assistant' as const,
        content: '发送失败，请重试。',
        status: 'failed' as const,
        error_detail: 'submit_failed',
        citations: [],
        tool_trace: [],
      }]);
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [messages]);

  const runningAssistant = messages.find(m => m.role === 'assistant' && m.status === 'running');
  const visibleMessages = messages.filter((m) => {
    if (m.role !== 'assistant') return true;
    const hasContent = String(m.content || '').trim().length > 0;
    const hasTrace = Array.isArray(m.tool_trace) && m.tool_trace.length > 0;
    const hasCitations = Array.isArray(m.citations) && m.citations.length > 0;
    const hasError = String(m.error_detail || '').trim().length > 0 || m.status === 'failed';
    const isRunning = m.status === 'running';
    return hasContent || hasTrace || hasCitations || hasError || isRunning;
  });

  return (
    <div className="flex-1 flex overflow-hidden">
      <aside className="w-72 border-r border-outline-variant bg-surface-container-low flex flex-col">
        <div className="p-4 border-b border-outline-variant flex justify-between items-center">
          <h2 className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono">会话</h2>
          <button onClick={createSession} disabled={creating} className="text-secondary hover:bg-secondary-container/20 p-1.5 rounded-lg transition-all disabled:opacity-40">
            <PlusSquare className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`p-3 rounded-xl transition-all cursor-pointer group ${activeSessionId === s.session_id ? 'bg-surface-container-lowest border border-outline-variant precision-shadow' : 'hover:bg-surface-container border border-transparent'}`}
              onClick={() => loadSession(s.session_id)}
            >
              <div className="flex items-center justify-between">
                <p className={`text-sm font-medium truncate flex-1 ${activeSessionId === s.session_id ? 'text-on-surface' : 'text-on-surface-variant'}`}>{s.title || '新会话'}</p>
                <button onClick={(e) => { e.stopPropagation(); deleteSession(s.session_id); }} className="opacity-0 group-hover:opacity-100 text-outline hover:text-error transition-all ml-2">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="text-xs text-outline font-mono mt-1 flex items-center gap-1.5">
                <Clock className="w-3 h-3" />
                {s.default_mode}
              </p>
            </div>
          ))}
        </div>
      </aside>

      <section className="flex-1 flex flex-col bg-surface-container-lowest relative overflow-hidden">
        {!activeSessionId ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center space-y-4">
              <div className="w-16 h-16 bg-secondary-container/30 border border-secondary/20 rounded-2xl flex items-center justify-center mx-auto">
                <Bot className="w-8 h-8 text-secondary" />
              </div>
              <h3 className="text-lg font-medium text-on-surface">选择或创建会话</h3>
              <p className="text-sm text-on-surface-variant">从侧边栏选择会话或创建新会话</p>
              <button onClick={createSession} disabled={creating} className="bg-secondary text-on-secondary px-6 py-2.5 rounded-xl text-sm font-bold hover:opacity-90 transition-all flex items-center gap-2 mx-auto disabled:opacity-50">
                {creating ? <span className="inline-block w-4 h-4 border-2 border-on-secondary/30 border-t-on-secondary rounded-full animate-spin" /> : <PlusSquare className="w-4 h-4" />}
                {creating ? '创建中...' : '新会话'}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div ref={feedRef} className="flex-1 overflow-y-auto px-8 py-6 space-y-6 custom-scrollbar">
              {visibleMessages.map((m) => (
                <div key={m.message_id} className={`flex gap-4 ${m.role === 'user' ? 'justify-end' : ''}`}>
                  {m.role === 'assistant' && (
                    <div className="w-8 h-8 rounded-lg bg-secondary-container/30 border border-secondary/20 flex items-center justify-center flex-shrink-0">
                      <Bot className="w-5 h-5 text-secondary" />
                    </div>
                  )}
                  <div className={`max-w-[80%] ${m.role === 'user' ? 'bg-primary-container text-on-primary rounded-2xl rounded-tr-none px-6 py-4 shadow-lg border border-primary/10' : 'space-y-3'}`}>
                    {m.role === 'assistant' ? (
                      <>
                        {(!Array.isArray(m.tool_trace) || m.tool_trace.length === 0) && (
                          <div className="font-serif text-[15px] text-on-surface leading-relaxed antialiased">
                            <div
                              className="prose prose-sm max-w-none prose-p:my-2 prose-pre:my-2 prose-code:before:content-none prose-code:after:content-none"
                              dangerouslySetInnerHTML={renderMarkdown(
                                ensureCitationMarkers(m.content || '', Array.isArray(m.citations) ? m.citations : []) || (m.status === 'running' ? '思考中...' : ''),
                              )}
                            />
                            {m.status === 'running' && <span className="animate-pulse-soft"> ▌</span>}
                          </div>
                        )}
                        {m.status === 'failed' && m.error_detail && (
                          <div className="text-sm text-error bg-error-container/10 border border-error/20 rounded-lg px-3 py-2 mt-2">
                            失败: {m.error_detail}
                          </div>
                        )}
                        {Array.isArray(m.citations) && m.citations.length > 0 && (
                          <div className="mt-4 rounded-xl border border-outline-variant bg-surface-container-low p-3 space-y-2">
                            <div className="text-xs font-mono uppercase tracking-widest text-outline">参考文献</div>
                            {m.citations.map((c, idx) => (
                              <button
                                key={`${m.message_id}-c-${idx}`}
                                onClick={() => openCitationInReader(c)}
                                className="w-full text-left bg-surface-container-lowest border border-outline-variant rounded-xl px-3 py-2 hover:border-secondary transition-all group"
                              >
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="text-[13px] font-mono font-bold bg-secondary-container/20 text-secondary px-1.5 py-0.5 rounded border border-secondary/20">[{idx + 1}]</span>
                                  <span className="text-xs text-on-surface-variant group-hover:text-secondary transition-colors truncate">{c.title || c.paper_id || c.id || '引用'}</span>
                                </div>
                                <div className="text-[13px] text-outline line-clamp-2">
                                  {String(c.text || normalizeCitationText(c).paragraph || normalizeCitationText(c).sentence || '').trim()}
                                </div>
                              </button>
                            ))}
                          </div>
                        )}
                        {Array.isArray(m.tool_trace) && m.tool_trace.length > 0 && (
                          <div className="space-y-2 mt-2">
                            {(() => {
                              const timelineRows = m.tool_trace
                                .map((t) => toTimelineRow((t && typeof t === 'object') ? (t as Record<string, unknown>) : {}))
                                .filter((x): x is TimelineRow => !!x);
                              return (
                                <>
                                  {timelineRows.map((timeline, idx) => {
                                    const itemKey = `${m.message_id}-inline-${idx}`;
                                    const itemExpanded = !!expandedToolItems[itemKey];
                                    if (timeline.kind === 'delta_text') {
                                      return (
                                        <div key={idx} className="text-sm text-on-surface-variant whitespace-pre-wrap break-words px-1 py-0.5">
                                          {timeline.detail}
                                        </div>
                                      );
                                    }
                                    return (
                                      <div key={idx} className="rounded-lg border border-outline-variant/50 bg-surface-container-lowest text-xs font-mono overflow-hidden">
                                        <button
                                          onClick={() => setExpandedToolItems(prev => ({ ...prev, [itemKey]: !itemExpanded }))}
                                          className="w-full text-left p-2.5 flex items-center justify-between hover:bg-surface-container-low transition-colors"
                                        >
                                          <span className={`${timeline.state === 'failed' ? 'text-error' : timeline.state === 'running' ? 'text-amber-600' : 'text-secondary'} font-bold truncate`}>{timeline.title}</span>
                                          <ChevronDown className={`w-3.5 h-3.5 text-outline transition-transform ${itemExpanded ? 'rotate-180' : ''}`} />
                                        </button>
                                        {itemExpanded && (
                                          <div className="px-2.5 pb-2.5 space-y-2">
                                            <div className="bg-surface-container-low p-2 rounded border border-outline-variant/30">
                                              <div className="text-[13px] text-on-surface-variant break-words whitespace-pre-wrap">{timeline.detail}</div>
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </>
                              );
                            })()}
                          </div>
                        )}
                      </>
                    ) : (
                      <p className="leading-relaxed text-[15px]">{m.content}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="p-6 border-t border-outline-variant bg-surface-container-lowest">
              <div className="max-w-4xl mx-auto space-y-3">
                <div className="flex items-center gap-1 p-1 bg-surface-container-low w-fit rounded-xl border border-outline-variant">
                  <button
                    onClick={() => setMode('fast')}
                    className={`px-4 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1.5 transition-all ${mode === 'fast' ? 'bg-surface-container-lowest text-on-surface precision-shadow' : 'text-outline hover:text-on-surface-variant'}`}
                  >
                    <Zap className="w-3.5 h-3.5" />
                    快速
                  </button>
                  <button
                    onClick={() => setMode('agent')}
                    className={`px-4 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1.5 transition-all ${mode === 'agent' ? 'bg-surface-container-lowest text-on-surface precision-shadow' : 'text-outline hover:text-on-surface-variant'}`}
                  >
                    <Activity className="w-3.5 h-3.5" />
                    智能
                  </button>
                </div>

                <div className="relative bg-surface-container-lowest border border-outline-variant rounded-2xl precision-shadow focus-within:ring-2 focus-within:ring-secondary/20 transition-all overflow-hidden">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                    className="w-full p-4 text-sm border-none focus:ring-0 resize-none font-sans min-h-[80px] outline-none bg-transparent"
                    placeholder="询问您的研究问题..."
                    disabled={submitting || !!runningAssistant}
                    rows={3}
                  />
                  <div className="flex items-center justify-between px-4 pb-3">
                    <div />
                    <button
                      onClick={sendMessage}
                      disabled={submitting || !input.trim() || !!runningAssistant}
                      className="bg-secondary text-on-secondary px-5 py-2 rounded-xl text-xs font-bold hover:opacity-90 transition-all flex items-center gap-2 shadow-lg shadow-secondary/10 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      发送
                      <Send className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </section>

      {citationModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setCitationModal(null)}>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest font-mono">引用详情</h3>
              <button onClick={() => setCitationModal(null)} className="text-outline hover:text-on-surface transition-colors"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-4">
              {citationModal.sentence && (
                <div>
                  <span className="text-xs font-mono text-secondary uppercase tracking-widest block mb-2">命中句子</span>
                  <pre className="whitespace-pre-wrap text-sm text-on-surface bg-surface-container-low p-4 rounded-xl border border-outline-variant">{citationModal.sentence}</pre>
                </div>
              )}
              {citationModal.paragraph && (
                <div>
                  <span className="text-xs font-mono text-secondary uppercase tracking-widest block mb-2">段落</span>
                  <pre className="whitespace-pre-wrap text-sm text-on-surface bg-surface-container-low p-4 rounded-xl border border-outline-variant max-h-60 overflow-auto custom-scrollbar">{citationModal.paragraph}</pre>
                </div>
              )}
              <div className="text-[13px] text-outline font-mono">
                {citationModal.paper_id && <span>论文: {citationModal.paper_id}</span>}
                {citationModal.title && <span className="ml-4">{citationModal.title}</span>}
              </div>
            </div>
          </div>
        </div>
      )}

      {loadingSession && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl px-6 py-4 shadow-2xl flex items-center gap-3">
            <div className="w-4 h-4 border-2 border-secondary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium text-on-surface">加载会话中...</span>
          </div>
        </div>
      )}
    </div>
  );
}
