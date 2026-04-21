import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";

async function jsonFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(payload.error || `http_${resp.status}`);
  }
  return payload;
}

function App() {
  const [sessions, setSessions] = useState([]);
  const [loadingSessions, setLoadingSessions] = useState(false);

  async function refreshSessions() {
    setLoadingSessions(true);
    try {
      const payload = await jsonFetch("/chat/sessions");
      setSessions(Array.isArray(payload.sessions) ? payload.sessions : []);
    } catch {
      setSessions([]);
    } finally {
      setLoadingSessions(false);
    }
  }

  useEffect(() => {
    refreshSessions();
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-dot" />
          <div>
            <h1>KN Chat</h1>
            <p>Variables + RAG + Agent</p>
          </div>
        </div>
        <SessionCreate onCreated={refreshSessions} />
        <div className="side-links">
          <Link to="/search">变量搜索</Link>
        </div>
        <div className="session-list">
          <div className="section-title">会话</div>
          {loadingSessions ? <div className="muted">加载中...</div> : null}
          {sessions.map((s) => (
            <Link className="session-item" key={s.session_id} to={`/chat/${s.session_id}`}>
              <div>{s.title || "新会话"}</div>
              <small>{s.default_mode || "fast"}</small>
            </Link>
          ))}
        </div>
      </aside>
      <main className="main-pane">
        <Routes>
          <Route path="/search" element={<SearchPage onSessionMutated={refreshSessions} />} />
          <Route path="/chat/:sessionId" element={<ChatPage onSessionMutated={refreshSessions} />} />
          <Route path="*" element={<SearchPage onSessionMutated={refreshSessions} />} />
        </Routes>
      </main>
    </div>
  );
}

function SessionCreate({ onCreated }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  async function createSession() {
    setBusy(true);
    try {
      const payload = await jsonFetch("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ title: "新会话", default_mode: "fast" })
      });
      onCreated();
      navigate(`/chat/${payload.session_id}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="new-chat-btn" onClick={createSession} disabled={busy}>
      {busy ? "创建中..." : "新建会话"}
    </button>
  );
}

function SearchPage({ onSessionMutated }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function runSearch() {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    setBusy(true);
    try {
      const payload = await jsonFetch(`/graph/search?mode=variable&query=${encodeURIComponent(query)}&limit=12`);
      setResults(Array.isArray(payload.results) ? payload.results : []);
    } finally {
      setBusy(false);
    }
  }

  async function askFromSearch(text) {
    const session = await jsonFetch("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: text.slice(0, 36), default_mode: "fast" })
    });
    await jsonFetch(`/chat/sessions/${session.session_id}/messages`, {
      method: "POST",
      body: JSON.stringify({
        content: text,
        mode: "fast",
        provider: "glm",
        model: "glm-4.5-flash",
        stream: true
      })
    });
    onSessionMutated();
    navigate(`/chat/${session.session_id}`);
  }

  return (
    <section className="page page-search">
      <header>
        <h2>变量搜索</h2>
        <p>先搜变量，再一键转 Chat 问答。</p>
      </header>
      <div className="search-row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入变量或问题..."
          onKeyDown={(e) => {
            if (e.key === "Enter") runSearch();
          }}
        />
        <button onClick={runSearch} disabled={busy}>
          {busy ? "搜索中..." : "搜索"}
        </button>
        <button
          className="outline-btn"
          onClick={() => askFromSearch(query)}
          disabled={!query.trim()}
        >
          直接提问
        </button>
      </div>
      <div className="result-grid">
        {results.map((item) => (
          <article key={`${item.kind}-${item.id}`} className="result-card">
            <h3>{item.title || item.id}</h3>
            <p>类型：{item.kind}</p>
            <p>评分：{item.score}</p>
            <button onClick={() => askFromSearch(`请解释变量“${item.title || item.id}”的研究发现，并给出证据。`)}>
              用这个变量提问
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function ChatPage({ onSessionMutated }) {
  const { sessionId } = useParams();
  const [messages, setMessages] = useState([]);
  const [session, setSession] = useState(null);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState("fast");
  const [provider, setProvider] = useState("glm");
  const [model, setModel] = useState("glm-4.5-flash");
  const [submitting, setSubmitting] = useState(false);
  const streamRef = useRef(null);

  const runningAssistant = useMemo(
    () => messages.find((m) => m.role === "assistant" && m.status === "running"),
    [messages]
  );

  useEffect(() => {
    let mounted = true;
    async function loadSession() {
      if (!sessionId) return;
      const payload = await jsonFetch(`/chat/sessions/${sessionId}`);
      if (!mounted) return;
      setSession(payload.session || null);
      setMessages(Array.isArray(payload.messages) ? payload.messages : []);
      if (payload.session?.default_mode) setMode(payload.session.default_mode);
    }
    loadSession().catch(() => {
      setSession(null);
      setMessages([]);
    });
    return () => {
      mounted = false;
      if (streamRef.current) {
        streamRef.current.close();
        streamRef.current = null;
      }
    };
  }, [sessionId]);

  function attachStream(url, assistantMessageId) {
    if (streamRef.current) {
      streamRef.current.close();
    }
    const es = new EventSource(url);
    streamRef.current = es;

    es.addEventListener("delta", (evt) => {
      const payload = JSON.parse(evt.data || "{}");
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === assistantMessageId
            ? { ...m, content: `${m.content || ""}${payload.text || ""}`, status: "running" }
            : m
        )
      );
    });

    es.addEventListener("tool_call", (evt) => {
      const payload = JSON.parse(evt.data || "{}");
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === assistantMessageId
            ? { ...m, tool_trace: [...(m.tool_trace || []), payload], status: "running" }
            : m
        )
      );
    });

    es.addEventListener("completed", (evt) => {
      const payload = JSON.parse(evt.data || "{}");
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === assistantMessageId
            ? {
                ...m,
                content: payload.answer || m.content || "",
                citations: payload.citations || [],
                retrieval: payload.retrieval_trace || {},
                tool_trace: payload.tool_trace || m.tool_trace || [],
                status: "completed"
              }
            : m
        )
      );
      es.close();
      streamRef.current = null;
      onSessionMutated();
    });

    es.addEventListener("failed", (evt) => {
      const payload = JSON.parse(evt.data || "{}");
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === assistantMessageId ? { ...m, status: "failed", error_detail: payload.error || "failed" } : m
        )
      );
      es.close();
      streamRef.current = null;
    });
  }

  async function sendMessage() {
    if (!sessionId || !input.trim() || submitting || runningAssistant) return;
    const content = input.trim();
    setSubmitting(true);
    try {
      const payload = await jsonFetch(`/chat/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          content,
          mode,
          provider,
          model,
          stream: true
        })
      });
      setInput("");
      setMessages((prev) => [
        ...prev,
        { message_id: payload.user_message_id, role: "user", content, status: "completed" },
        {
          message_id: payload.assistant_message_id,
          role: "assistant",
          content: "",
          status: "running",
          citations: [],
          tool_trace: []
        }
      ]);
      attachStream(payload.stream_url, payload.assistant_message_id);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page page-chat">
      <header className="chat-header">
        <div>
          <h2>{session?.title || "会话"}</h2>
          <p>默认模式：{session?.default_mode || "fast"}</p>
        </div>
        <div className="chat-controls">
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="fast">快速模式</option>
            <option value="agent">Agent 模式</option>
          </select>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="glm">GLM</option>
            <option value="deepseek">DeepSeek</option>
          </select>
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="model id" />
        </div>
      </header>
      <div className="chat-feed">
        {messages.map((m) => (
          <article key={m.message_id} className={`bubble ${m.role}`}>
            <div className="bubble-role">{m.role === "user" ? "你" : "助手"}</div>
            <div className="bubble-content">{m.content || (m.status === "running" ? "思考中..." : "")}</div>
            {Array.isArray(m.citations) && m.citations.length > 0 ? (
              <div className="citations">
                {m.citations.map((c, idx) => (
                  <span key={`${m.message_id}-c-${idx}`}>[{idx + 1}] {c.id || c.paper_id || c.title || "证据"}</span>
                ))}
              </div>
            ) : null}
            {m.status === "failed" ? <div className="error-text">失败：{m.error_detail || "unknown"}</div> : null}
          </article>
        ))}
      </div>
      <footer className="chat-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入你的问题..."
          rows={3}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
        />
        <button onClick={sendMessage} disabled={submitting || !input.trim() || Boolean(runningAssistant)}>
          发送
        </button>
      </footer>
    </section>
  );
}

export default App;
