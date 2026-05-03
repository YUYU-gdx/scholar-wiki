import { useCallback, useEffect, useRef, useState } from 'react';
import { Send, PanelRightClose, PanelRightOpen, Copy, BookOpen } from 'lucide-react';
import { api } from '../../api';
import type { ChatMessage } from '../../types';

interface ReaderChatSidebarProps {
  paperId: string;
  libraryId: string;
  absolutePath: string;
  isOpen: boolean;
  onToggle: () => void;
}

export default function ReaderChatSidebar({
  paperId,
  libraryId,
  absolutePath,
  isOpen,
  onToggle,
}: ReaderChatSidebarProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const streamRef = useRef<EventSource | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);

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
    es.addEventListener('completed', (evt) => {
      try {
        const payload = JSON.parse(evt.data || '{}');
        setMessages((prev) => prev.map((m) => (
          m.message_id === messageId ? { ...m, content: payload.answer || m.content || '', status: 'completed' } : m
        )));
      } catch {
        // ignore
      }
      es.close();
      streamRef.current = null;
    });
    es.addEventListener('failed', () => {
      setMessages((prev) => prev.map((m) => (
        m.message_id === messageId ? { ...m, status: 'failed', error_detail: 'stream_failed' } : m
      )));
      es.close();
      streamRef.current = null;
    });
    streamRef.current = es;
  }, []);

  const sendMessage = useCallback(async () => {
    const question = input.trim();
    if (!question || submitting) return;
    setInput('');
    setSubmitting(true);
    try {
      const sid = await ensureSession();
      const contextSuffix = `\n\n目前用户正在文献阅读器中进行对话，当前文献的绝对路径：${absolutePath || '未知路径'}`;
      const finalContent = `${question}${contextSuffix}`;
      const res = await api.chat.sendMessage(sid, finalContent, libraryId, 'agent', 'codex', 'codex-local', true);
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
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      attachStream(sid, res.assistant_message_id);
    } finally {
      setSubmitting(false);
    }
  }, [absolutePath, attachStream, ensureSession, input, libraryId, submitting]);

  useEffect(() => {
    setSessionId(null);
    setMessages([]);
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
  }, [paperId, libraryId]);

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [messages]);

  if (!isOpen) {
    return (
      <button
        className="absolute right-4 top-28 px-2.5 py-1.5 text-[10px] font-mono bg-surface-container border border-outline-variant rounded-lg hover:bg-surface-container-low z-10 shadow-sm inline-flex items-center gap-1"
        onClick={onToggle}
      >
        <PanelRightOpen className="w-3 h-3" />
        Reader Chat
      </button>
    );
  }

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
        <div className="mt-2 p-2 rounded-lg border border-outline-variant bg-surface-container-lowest">
          <div className="text-[10px] text-outline mb-1">当前文献绝对路径</div>
          <div className="text-[11px] text-on-surface-variant break-all">{absolutePath || '未知路径'}</div>
          <button
            className="mt-2 text-[10px] px-2 py-1 rounded border border-outline-variant hover:bg-surface-container inline-flex items-center gap-1"
            onClick={() => navigator.clipboard?.writeText(absolutePath || '')}
          >
            <Copy className="w-3 h-3" />
            复制路径
          </button>
        </div>
      </div>

      <div ref={feedRef} className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
        {messages.length === 0 && (
          <div className="text-xs text-on-surface-variant p-3 border border-outline-variant rounded-lg bg-surface-container-low">
            在这里提问将自动附带当前文献路径上下文，便于模型结合当前文献内容回答。
          </div>
        )}
        {messages.map((m) => (
          <div key={m.message_id} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div className={`max-w-[92%] px-3 py-2 rounded-xl text-xs leading-relaxed whitespace-pre-wrap ${
              m.role === 'user'
                ? 'bg-primary-container text-on-primary'
                : 'bg-surface-container border border-outline-variant text-on-surface'
            }`}>
              {m.role === 'assistant' && !m.content ? '正在思考...' : m.content}
              {m.status === 'failed' && <div className="mt-2 text-error">消息流失败，请重试。</div>}
            </div>
          </div>
        ))}
      </div>

      <div className="p-4 border-t border-outline-variant bg-surface-container-low">
        <div className="text-[10px] text-outline mb-2">发送时会自动拼接文献绝对路径提示</div>
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
