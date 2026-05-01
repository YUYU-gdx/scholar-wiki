import { useState, useEffect, useRef, useCallback } from 'react';
import { PlusSquare, Bot, User, Send, Activity, CheckCircle, Clock, Trash2, RotateCcw, X, ChevronDown, Zap } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { ChatSession, ChatMessage, Citation as CitationType } from '../types';

export default function ChatView() {
  const { sessions, setSessions, activeSessionId, setActiveSessionId, activeLibraryId } = useApp();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<'fast' | 'agent'>('agent');
  const [provider, setProvider] = useState('codex');
  const [model, setModel] = useState('codex-local');
  const [submitting, setSubmitting] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [showModeSwitcher, setShowModeSwitcher] = useState(false);
  const [citationModal, setCitationModal] = useState<CitationType | null>(null);
  const streamRef = useRef<EventSource | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);

  const activeSession = sessions.find(s => s.session_id === activeSessionId);

  const refreshSessions = useCallback(async () => {
    try {
      const res = await api.chat.listSessions(activeLibraryId);
      setSessions(res.sessions || []);
    } catch { /* ignore */ }
  }, [activeLibraryId, setSessions]);

  useEffect(() => { refreshSessions(); }, [refreshSessions]);

  const loadSession = useCallback(async (sessionId: string) => {
    setLoadingSession(true);
    try {
      const res = await api.chat.getSession(sessionId, activeLibraryId);
      setMessages(res.messages || []);
      setActiveSessionId(sessionId);
      if (res.session?.default_mode) setMode(res.session.default_mode as 'fast' | 'agent');
    } catch { setMessages([]); }
    finally { setLoadingSession(false); }
  }, [activeLibraryId, setActiveSessionId]);

  const createSession = async () => {
    try {
      const session = await api.chat.createSession('新会话', activeLibraryId, mode);
      setSessions(prev => [session, ...prev]);
      setActiveSessionId(session.session_id);
      setMessages([]);
    } catch { /* ignore */ }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      await api.chat.deleteSession(sessionId, activeLibraryId);
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
            ? { ...m, tool_trace: [...(m.tool_trace || []), payload], status: 'running' as const }
            : m
        ));
      } catch { /* ignore */ }
    });

    es.addEventListener('completed', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages(prev => prev.map(m =>
          m.message_id === messageId
            ? { ...m, content: payload.answer || m.content || '', citations: payload.citations || [], retrieval: payload.retrieval_trace || {}, tool_trace: payload.tool_trace || m.tool_trace || [], status: 'completed' as const }
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

  return (
    <div className="flex-1 flex overflow-hidden">
      <aside className="w-72 border-r border-outline-variant bg-surface-container-low flex flex-col">
        <div className="p-4 border-b border-outline-variant flex justify-between items-center">
          <h2 className="text-[10px] font-bold text-on-surface uppercase tracking-widest font-mono">Sessions</h2>
          <button onClick={createSession} className="text-secondary hover:bg-secondary-container/20 p-1.5 rounded-lg transition-all">
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
              <p className="text-[10px] text-outline font-mono mt-1 flex items-center gap-1.5">
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
              <h3 className="text-lg font-medium text-on-surface">Select or create a session</h3>
              <p className="text-sm text-on-surface-variant">Choose a session from the sidebar or create a new one.</p>
              <button onClick={createSession} className="bg-secondary text-on-secondary px-6 py-2.5 rounded-xl text-sm font-bold hover:opacity-90 transition-all flex items-center gap-2 mx-auto">
                <PlusSquare className="w-4 h-4" />
                New Session
              </button>
            </div>
          </div>
        ) : (
          <>
            <div ref={feedRef} className="flex-1 overflow-y-auto px-8 py-6 space-y-6 custom-scrollbar">
              {messages.map((m) => (
                <div key={m.message_id} className={`flex gap-4 ${m.role === 'user' ? 'justify-end' : ''}`}>
                  {m.role === 'assistant' && (
                    <div className="w-8 h-8 rounded-lg bg-secondary-container/30 border border-secondary/20 flex items-center justify-center flex-shrink-0">
                      <Bot className="w-5 h-5 text-secondary" />
                    </div>
                  )}
                  <div className={`max-w-[80%] ${m.role === 'user' ? 'bg-primary-container text-on-primary rounded-2xl rounded-tr-none px-6 py-4 shadow-lg border border-primary/10' : 'space-y-3'}`}>
                    {m.role === 'assistant' ? (
                      <>
                        <div className="font-serif text-[15px] text-on-surface leading-relaxed antialiased whitespace-pre-wrap">
                          {m.content || (m.status === 'running' ? 'Thinking...' : '')}
                          {m.status === 'running' && <span className="animate-pulse-soft"> ▌</span>}
                        </div>
                        {m.status === 'failed' && m.error_detail && (
                          <div className="text-sm text-error bg-error-container/10 border border-error/20 rounded-lg px-3 py-2 mt-2">
                            失败: {m.error_detail}
                          </div>
                        )}
                        {Array.isArray(m.citations) && m.citations.length > 0 && (
                          <div className="grid grid-cols-1 gap-2 mt-3">
                            {m.citations.map((c, idx) => (
                              <button
                                key={`${m.message_id}-c-${idx}`}
                                onClick={() => setCitationModal(c)}
                                className="text-left bg-surface-container-low border border-outline-variant rounded-xl px-3 py-2 hover:border-secondary transition-all group"
                              >
                                <div className="flex items-center gap-2">
                                  <span className="text-[9px] font-mono font-bold bg-secondary-container/20 text-secondary px-1.5 py-0.5 rounded border border-secondary/20">[{idx + 1}]</span>
                                  <span className="text-xs text-on-surface-variant group-hover:text-secondary transition-colors truncate">{c.title || c.paper_id || c.id || 'Citation'}</span>
                                </div>
                              </button>
                            ))}
                          </div>
                        )}
                        {Array.isArray(m.tool_trace) && m.tool_trace.length > 0 && (
                          <div className="space-y-1 mt-2">
                            {m.tool_trace.map((t, idx) => (
                              <div key={idx} className="text-[10px] font-mono text-on-surface-variant bg-surface-container-low px-2 py-1 rounded border border-outline-variant/50">
                                <span className="text-secondary font-bold">{t.name || 'tool'}</span>
                                {t.arguments && <span className="ml-2 text-outline truncate">{typeof t.arguments === 'string' ? t.arguments.slice(0, 80) : JSON.stringify(t.arguments).slice(0, 80)}</span>}
                              </div>
                            ))}
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
                    Fast
                  </button>
                  <button
                    onClick={() => setMode('agent')}
                    className={`px-4 py-1.5 text-xs font-bold rounded-lg flex items-center gap-1.5 transition-all ${mode === 'agent' ? 'bg-surface-container-lowest text-on-surface precision-shadow' : 'text-outline hover:text-on-surface-variant'}`}
                  >
                    <Activity className="w-3.5 h-3.5" />
                    Agent
                  </button>
                </div>

                <div className="relative bg-surface-container-lowest border border-outline-variant rounded-2xl precision-shadow focus-within:ring-2 focus-within:ring-secondary/20 transition-all overflow-hidden">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                    className="w-full p-4 text-sm border-none focus:ring-0 resize-none font-sans min-h-[80px] outline-none bg-transparent"
                    placeholder="Ask about your research..."
                    disabled={submitting || !!runningAssistant}
                    rows={3}
                  />
                  <div className="flex items-center justify-between px-4 pb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-outline uppercase tracking-widest">Mode: {mode}</span>
                      <div className="h-3 w-px bg-outline-variant"></div>
                      <span className="text-[10px] font-mono text-outline uppercase tracking-widest">Library: {activeLibraryId}</span>
                    </div>
                    <button
                      onClick={sendMessage}
                      disabled={submitting || !input.trim() || !!runningAssistant}
                      className="bg-secondary text-on-secondary px-5 py-2 rounded-xl text-xs font-bold hover:opacity-90 transition-all flex items-center gap-2 shadow-lg shadow-secondary/10 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Send
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
              <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest font-mono">Citation Detail</h3>
              <button onClick={() => setCitationModal(null)} className="text-outline hover:text-on-surface transition-colors"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-4">
              {citationModal.sentence && (
                <div>
                  <span className="text-[10px] font-mono text-secondary uppercase tracking-widest block mb-2">Hit Sentence</span>
                  <pre className="whitespace-pre-wrap text-sm text-on-surface bg-surface-container-low p-4 rounded-xl border border-outline-variant">{citationModal.sentence}</pre>
                </div>
              )}
              {citationModal.paragraph && (
                <div>
                  <span className="text-[10px] font-mono text-secondary uppercase tracking-widest block mb-2">Paragraph</span>
                  <pre className="whitespace-pre-wrap text-sm text-on-surface bg-surface-container-low p-4 rounded-xl border border-outline-variant max-h-60 overflow-auto custom-scrollbar">{citationModal.paragraph}</pre>
                </div>
              )}
              <div className="text-[11px] text-outline font-mono">
                {citationModal.paper_id && <span>Paper: {citationModal.paper_id}</span>}
                {citationModal.title && <span className="ml-4">{citationModal.title}</span>}
              </div>
            </div>
          </div>
        </div>
      )}

      <aside className="w-72 border-l border-outline-variant bg-surface-container-low flex flex-col">
        <div className="p-4 border-b border-outline-variant flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-secondary" />
            <h2 className="text-[10px] font-bold text-on-surface uppercase tracking-widest font-mono">Process Trace</h2>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
          {messages.filter(m => m.role === 'assistant' && m.tool_trace && m.tool_trace.length > 0).slice(-1).map(m => (
            <div key={m.message_id} className="space-y-3">
              <div className="text-[10px] font-mono text-outline uppercase tracking-widest font-bold mb-2">Tool Calls</div>
              {(m.tool_trace || []).map((t, idx) => (
                <div key={idx} className="p-2.5 rounded-lg border border-outline-variant/50 bg-surface-container-lowest text-[10px] font-mono">
                  <span className="text-secondary font-bold">{t.name || 'tool'}</span>
                  <div className="text-on-surface-variant mt-1">{typeof t.arguments === 'string' ? t.arguments.slice(0, 100) : JSON.stringify(t.arguments).slice(0, 100)}</div>
                </div>
              ))}
            </div>
          ))}
          {messages.length === 0 && (
            <div className="text-center text-outline text-[11px] font-mono mt-8">
              Send a message to see process trace.
            </div>
          )}
        </div>
      </aside>

      {loadingSession && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl px-6 py-4 shadow-2xl flex items-center gap-3">
            <div className="w-4 h-4 border-2 border-secondary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium text-on-surface">Loading session...</span>
          </div>
        </div>
      )}
    </div>
  );
}