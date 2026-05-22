import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Send, PanelRightClose, PanelRightOpen, BookOpen, ChevronDown } from 'lucide-react';
import { api } from '../../api';
import type { ChatMessage } from '../../types';
import { renderMarkdownToHtmlSync } from '../markdown/markdownRenderer';
import { toTimelineRow } from './readerToolTrace';

interface ReaderChatSidebarProps {
  paperId: string;
  libraryId: string;
  absolutePath: string;
  isOpen: boolean;
  onToggle: () => void;
  showClosedToggle?: boolean;
}

export default function ReaderChatSidebar({
  paperId,
  libraryId,
  absolutePath,
  isOpen,
  onToggle,
  showClosedToggle = true,
}: ReaderChatSidebarProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [chatError, setChatError] = useState('');
  const [expandedToolItems, setExpandedToolItems] = useState<Record<string, boolean>>({});
  const streamRef = useRef<EventSource | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const renderMarkdown = useCallback((text: string) => ({ __html: renderMarkdownToHtmlSync(text, { profile: 'chat' }) }), []);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const title = `Reader ${paperId}`;
    const session = await api.chat.createSession(title, libraryId, 'agent');
    setSessionId(session.session_id);
    return session.session_id;
  }, [libraryId, paperId, sessionId]);

  const attachStream = useCallback((sid: string, messageId: string) => {
    if (streamRef.current) streamRef.current.close();
    const es = api.chat.streamEvents(sid, messageId);

    es.addEventListener('delta', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId ? { ...m, content: `${m.content || ''}${payload.text || ''}`, status: 'running' } : m
        )));
      } catch {
        // ignore
      }
    });

    es.addEventListener('tool_call', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId
            ? { ...m, tool_trace: [...(m.tool_trace || []), { ...payload, event: 'tool_call' }], status: 'running' }
            : m
        )));
      } catch {
        // ignore
      }
    });

    const pushEvent = (evtName: string, evt: Event) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data || '{}');
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId
            ? { ...m, tool_trace: [...(m.tool_trace || []), { ...payload, event: evtName }], status: 'running' }
            : m
        )));
      } catch {
        // ignore
      }
    };

    es.addEventListener('agent_item_started', (evt) => pushEvent('agent_item_started', evt));
    es.addEventListener('agent_item_completed', (evt) => pushEvent('agent_item_completed', evt));
    es.addEventListener('agent_item_delta', (evt) => pushEvent('agent_item_delta', evt));
    es.addEventListener('status', (evt) => pushEvent('status', evt));
    es.addEventListener('citation', (evt) => pushEvent('citation', evt));

    es.addEventListener('completed', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId
            ? {
                ...m,
                content: payload.answer || m.content || '',
                tool_trace: Array.isArray(payload.tool_trace) && payload.tool_trace.length > 0
                  ? payload.tool_trace
                  : (m.tool_trace || []),
                status: 'completed',
              }
            : m
        )));
      } catch {
        // ignore
      }
      es.close();
      streamRef.current = null;
    });

    es.addEventListener('failed', (evt) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data || '{}');
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId ? { ...m, status: 'failed', error_detail: payload.error || 'stream_failed' } : m
        )));
      } catch {
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId ? { ...m, status: 'failed', error_detail: 'stream_failed' } : m
        )));
      }
      es.close();
      streamRef.current = null;
    });

    streamRef.current = es;
  }, []);

  const sendMessage = useCallback(async () => {
    const question = input.trim();
    if (!question || submitting) return;
    setInput('');
    setChatError('');
    setSubmitting(true);
    const pendingUserId = `pending_user_${Date.now()}`;
    setMessages((prev) => [...prev, {
      message_id: pendingUserId,
      session_id: sessionId || '',
      role: 'user',
      content: question,
      status: 'completed',
    }]);
    try {
      const sid = await ensureSession();
      const contextSuffix = `\n\n当前用户正在文献阅读器中进行对话，当前文献的绝对路径：${absolutePath || '未知路径'}`;
      const finalContent = `${question}${contextSuffix}`;
      const res = await api.chat.sendMessage(sid, finalContent, libraryId, 'agent', '', 'codex-local', true);
      const userMsg: ChatMessage = {
        message_id: res.user_message_id,
        session_id: sid,
        role: 'user',
        content: question,
        status: 'completed',
      };
      const assistantMsg: ChatMessage = {
        message_id: res.assistant_message_id,
        session_id: sid,
        role: 'assistant',
        content: '',
        status: 'running',
        tool_trace: [],
      };
      setMessages((prev) => [...prev.filter((m) => m.message_id !== pendingUserId), userMsg, assistantMsg]);
      attachStream(sid, res.assistant_message_id);
    } catch (err) {
      const detail = String((err as Error)?.message || err || 'submit_failed');
      setChatError(`发送失败: ${detail}`);
      setMessages((prev) => [...prev, {
        message_id: `err_${Date.now()}`,
        session_id: sessionId || '',
        role: 'assistant',
        content: '发送失败，请重试。',
        status: 'failed',
        error_detail: detail,
        tool_trace: [],
      }]);
    } finally {
      setSubmitting(false);
    }
  }, [absolutePath, attachStream, ensureSession, input, libraryId, sessionId, submitting]);

  useEffect(() => {
    setSessionId(null);
    setMessages([]);
    setChatError('');
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
  }, [paperId, libraryId]);

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [messages]);

  const visibleMessages = messages.filter((m) => {
    if (m.role !== 'assistant') return true;
    const hasContent = String(m.content || '').trim().length > 0;
    const hasTrace = Array.isArray(m.tool_trace) && m.tool_trace.length > 0;
    const hasError = String(m.error_detail || '').trim().length > 0 || m.status === 'failed';
    const isRunning = m.status === 'running';
    return hasContent || hasTrace || hasError || isRunning;
  });

  if (!isOpen && showClosedToggle) {
    return (
      <button
        className="absolute right-4 top-64 px-2.5 py-1.5 text-xs font-mono bg-surface-container border border-outline-variant rounded-lg hover:bg-surface-container-low z-10 shadow-sm inline-flex items-center gap-1"
        onClick={onToggle}
      >
        <PanelRightOpen className="w-3 h-3" />
        Reader Chat
      </button>
    );
  }

  if (!isOpen) return null;

  return (
    <aside className="w-[430px] border-l border-outline-variant bg-surface-container-lowest flex flex-col">
      <div className="px-4 py-3 border-b border-outline-variant bg-surface-container-low">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-secondary" />
            <div className="text-sm font-semibold text-on-surface">Reader Assistant</div>
          </div>
          <button
            className="text-xs px-2 py-1 border border-outline-variant rounded-lg hover:bg-surface-container inline-flex items-center gap-1"
            onClick={onToggle}
          >
            <PanelRightClose className="w-3 h-3" />
            收起
          </button>
        </div>
      </div>

      <div ref={feedRef} className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
        {visibleMessages.map((m) => (
          <div key={m.message_id} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div className={`max-w-[92%] px-3 py-2 rounded-xl text-xs leading-relaxed whitespace-pre-wrap ${
              m.role === 'user'
                ? 'bg-primary-container text-on-primary'
                : 'bg-surface-container border border-outline-variant text-on-surface'
            }`}>
              {m.role !== 'assistant' && m.content}
              {m.role === 'assistant' && (
                <div
                  className="prose prose-sm max-w-none prose-p:my-1.5 prose-pre:my-1.5 prose-code:before:content-none prose-code:after:content-none"
                  dangerouslySetInnerHTML={renderMarkdown(
                    String(m.content || '').trim()
                      ? m.content
                      : ((!Array.isArray(m.tool_trace) || m.tool_trace.length === 0) && m.status === 'running' ? 'Thinking...' : ''),
                  )}
                />
              )}
              {m.status === 'failed' && <div className="mt-2 text-error">消息流失败：{m.error_detail || 'stream_failed'}</div>}
              {m.role === 'assistant' && Array.isArray(m.tool_trace) && m.tool_trace.length > 0 && (
                <div className="space-y-2 mt-2">
                  {m.tool_trace
                    .map((t) => toTimelineRow((t && typeof t === 'object') ? (t as Record<string, unknown>) : {}))
                    .filter((x): x is NonNullable<ReturnType<typeof toTimelineRow>> => !!x)
                    .map((timeline, idx) => {
                      const itemKey = `${m.message_id}-inline-${idx}`;
                      const itemExpanded = !!expandedToolItems[itemKey];
                      if (timeline.kind === 'delta_text') {
                        return (
                          <div key={itemKey} className="text-xs text-on-surface-variant whitespace-pre-wrap break-words px-1 py-0.5">
                            {timeline.detail}
                          </div>
                        );
                      }
                      return (
                        <div key={itemKey} className="rounded-lg border border-outline-variant/50 bg-surface-container-lowest text-xs font-mono overflow-hidden">
                          <button
                            onClick={() => setExpandedToolItems((prev) => ({ ...prev, [itemKey]: !itemExpanded }))}
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
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="p-4 border-t border-outline-variant bg-surface-container-low">
        {chatError && <div className="mb-2 text-xs text-error bg-error-container/10 border border-error/20 rounded-lg px-2.5 py-2">{chatError}</div>}
        <div className="text-xs text-outline mb-2">发送时会自动拼接文献绝对路径提示</div>
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            rows={3}
            className="flex-1 p-2.5 text-xs border border-outline-variant rounded-lg resize-none bg-surface-container-lowest outline-none focus:ring-2 focus:ring-secondary/20"
            placeholder="请输入关于当前文献的问题..."
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || submitting}
            className="px-3 py-2.5 rounded-lg bg-secondary text-on-secondary disabled:opacity-50 inline-flex items-center gap-1"
          >
            <Send className="w-3.5 h-3.5" />
            发送
          </button>
        </div>
      </div>
    </aside>
  );
}
