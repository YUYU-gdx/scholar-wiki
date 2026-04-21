from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Protocol
import uuid


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(raw: object, fallback: Any) -> Any:
    text = str(raw or "").strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


class ChatStore(Protocol):
    def create_session(self, title: str, default_mode: str) -> dict[str, Any]: ...

    def list_sessions(self) -> list[dict[str, Any]]: ...

    def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    def create_message(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_message(self, message_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...

    def get_message(self, message_id: str) -> dict[str, Any] | None: ...

    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...


class InMemoryChatStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, dict[str, Any]] = {}
        self._session_messages: dict[str, list[str]] = defaultdict(list)

    def create_session(self, title: str, default_mode: str) -> dict[str, Any]:
        with self._lock:
            now = _now_iso()
            session_id = f"sess_{uuid.uuid4().hex}"
            row = {
                "session_id": session_id,
                "title": title.strip() or "新会话",
                "default_mode": default_mode,
                "created_at": now,
                "updated_at": now,
            }
            self._sessions[session_id] = dict(row)
            return dict(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._sessions.values())
            rows.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
            return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(session_id)
            return dict(row) if isinstance(row, dict) else None

    def create_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = dict(payload)
            self._messages[str(row["message_id"])] = row
            self._session_messages[str(row["session_id"])].append(str(row["message_id"]))
            session_id = str(row["session_id"])
            if session_id in self._sessions:
                self._sessions[session_id]["updated_at"] = _now_iso()
            return dict(row)

    def update_message(self, message_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            key = str(message_id)
            if key not in self._messages:
                raise KeyError(message_id)
            self._messages[key].update(dict(updates))
            self._messages[key]["updated_at"] = _now_iso()
            session_id = str(self._messages[key].get("session_id", ""))
            if session_id in self._sessions:
                self._sessions[session_id]["updated_at"] = _now_iso()
            return dict(self._messages[key])

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._messages.get(str(message_id))
            return dict(row) if isinstance(row, dict) else None

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._session_messages.get(str(session_id), []))
            rows = [dict(self._messages[mid]) for mid in ids if mid in self._messages]
            rows.sort(key=lambda x: str(x.get("created_at", "")))
            return rows


class PostgresChatStore:
    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn = dsn
        self._psycopg = psycopg
        self._ensure_schema()

    def _conn(self):
        return self._psycopg.connect(self._dsn)

    def _ensure_schema(self) -> None:
        ddl = """
        create table if not exists chat_sessions (
            session_id text primary key,
            title text not null default '',
            default_mode text not null default 'fast',
            created_at timestamptz not null,
            updated_at timestamptz not null
        );

        create table if not exists chat_messages (
            message_id text primary key,
            session_id text not null,
            role text not null,
            mode text not null default 'fast',
            provider text not null default '',
            model text not null default '',
            content text not null default '',
            citations_json text not null default '[]',
            retrieval_json text not null default '{}',
            tool_trace_json text not null default '[]',
            status text not null default 'completed',
            error_detail text not null default '',
            created_at timestamptz not null,
            updated_at timestamptz not null
        );
        create index if not exists idx_chat_messages_session_id on chat_messages(session_id, created_at);

        create table if not exists chat_events (
            event_id bigserial primary key,
            message_id text not null,
            event_type text not null,
            payload_json text not null default '{}',
            created_at timestamptz not null
        );
        create index if not exists idx_chat_events_message_id on chat_events(message_id, event_id);
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()

    def create_session(self, title: str, default_mode: str) -> dict[str, Any]:
        session_id = f"sess_{uuid.uuid4().hex}"
        now = _now_iso()
        row = {
            "session_id": session_id,
            "title": title.strip() or "新会话",
            "default_mode": default_mode,
            "created_at": now,
            "updated_at": now,
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into chat_sessions(session_id, title, default_mode, created_at, updated_at)
                    values (%(session_id)s, %(title)s, %(default_mode)s, %(created_at)s, %(updated_at)s)
                    """,
                    row,
                )
            conn.commit()
        return row

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select session_id, title, default_mode, created_at, updated_at
                    from chat_sessions
                    order by updated_at desc
                    """
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "session_id": row[0],
                    "title": row[1],
                    "default_mode": row[2],
                    "created_at": str(row[3]),
                    "updated_at": str(row[4]),
                }
            )
        return out

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select session_id, title, default_mode, created_at, updated_at from chat_sessions where session_id=%s",
                    (session_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "title": row[1],
            "default_mode": row[2],
            "created_at": str(row[3]),
            "updated_at": str(row[4]),
        }

    def create_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into chat_messages(
                        message_id, session_id, role, mode, provider, model, content, citations_json,
                        retrieval_json, tool_trace_json, status, error_detail, created_at, updated_at
                    )
                    values (
                        %(message_id)s, %(session_id)s, %(role)s, %(mode)s, %(provider)s, %(model)s, %(content)s, %(citations_json)s,
                        %(retrieval_json)s, %(tool_trace_json)s, %(status)s, %(error_detail)s, %(created_at)s, %(updated_at)s
                    )
                    """,
                    row,
                )
                cur.execute("update chat_sessions set updated_at=%s where session_id=%s", (_now_iso(), row["session_id"]))
            conn.commit()
        return row

    def update_message(self, message_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        payload = dict(updates)
        payload["updated_at"] = _now_iso()
        payload["message_id"] = message_id
        sets = ", ".join(f"{k}=%({k})s" for k in payload.keys() if k != "message_id")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"update chat_messages set {sets} where message_id=%(message_id)s", payload)
                if cur.rowcount <= 0:
                    raise KeyError(message_id)
            conn.commit()
        row = self.get_message(message_id)
        if row is None:
            raise KeyError(message_id)
        return row

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select message_id, session_id, role, mode, provider, model, content, citations_json, retrieval_json,
                           tool_trace_json, status, error_detail, created_at, updated_at
                    from chat_messages where message_id=%s
                    """,
                    (message_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "message_id": row[0],
            "session_id": row[1],
            "role": row[2],
            "mode": row[3],
            "provider": row[4],
            "model": row[5],
            "content": row[6],
            "citations_json": row[7],
            "retrieval_json": row[8],
            "tool_trace_json": row[9],
            "status": row[10],
            "error_detail": row[11],
            "created_at": str(row[12]),
            "updated_at": str(row[13]),
        }

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select message_id, session_id, role, mode, provider, model, content, citations_json, retrieval_json,
                           tool_trace_json, status, error_detail, created_at, updated_at
                    from chat_messages where session_id=%s order by created_at asc
                    """,
                    (session_id,),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "message_id": row[0],
                    "session_id": row[1],
                    "role": row[2],
                    "mode": row[3],
                    "provider": row[4],
                    "model": row[5],
                    "content": row[6],
                    "citations_json": row[7],
                    "retrieval_json": row[8],
                    "tool_trace_json": row[9],
                    "status": row[10],
                    "error_detail": row[11],
                    "created_at": str(row[12]),
                    "updated_at": str(row[13]),
                }
            )
        return out

    def append_event(self, message_id: str, event_type: str, payload_json: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into chat_events(message_id, event_type, payload_json, created_at)
                    values (%s, %s, %s, %s)
                    """,
                    (message_id, event_type, payload_json, _now_iso()),
                )
            conn.commit()

    def list_events(self, message_id: str, after_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select event_id, event_type, payload_json, created_at
                    from chat_events
                    where message_id=%s and event_id > %s
                    order by event_id asc
                    """,
                    (message_id, int(after_id)),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "event_id": int(row[0]),
                    "type": str(row[1]),
                    "payload": _safe_json(row[2], {}),
                    "created_at": str(row[3]),
                }
            )
        return out


@dataclass(slots=True)
class _EventState:
    events: list[dict[str, Any]]
    completed: bool
    failed: bool
    cond: threading.Condition


class EventHub:
    def __init__(self, db_store: PostgresChatStore | None = None) -> None:
        self._states: dict[str, _EventState] = {}
        self._lock = threading.Lock()
        self._db_store = db_store

    def _ensure(self, message_id: str) -> _EventState:
        with self._lock:
            if message_id not in self._states:
                self._states[message_id] = _EventState(events=[], completed=False, failed=False, cond=threading.Condition())
            return self._states[message_id]

    def publish(self, message_id: str, event_type: str, payload: dict[str, Any]) -> None:
        state = self._ensure(message_id)
        event = {"type": event_type, "payload": dict(payload), "created_at": _now_iso()}
        with state.cond:
            state.events.append(event)
            if event_type == "completed":
                state.completed = True
            if event_type == "failed":
                state.failed = True
            state.cond.notify_all()
        if self._db_store is not None:
            try:
                self._db_store.append_event(message_id, event_type, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

    def read_since(self, message_id: str, cursor: int, wait_seconds: float = 20.0) -> tuple[list[dict[str, Any]], int, bool]:
        state = self._ensure(message_id)
        with state.cond:
            if cursor >= len(state.events) and not state.completed and not state.failed:
                state.cond.wait(timeout=max(0.1, wait_seconds))
            events = state.events[cursor:]
            next_cursor = len(state.events)
            done = state.completed or state.failed
            return [dict(x) for x in events], next_cursor, done


class ModelRouter:
    def __init__(self) -> None:
        module_path = Path(__file__).resolve().parent / "llm" / "provider_registry.py"
        spec = __import__("importlib.util").util.spec_from_file_location(
            "smj_pipeline_llm_provider_registry_for_chat_service", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("provider_registry_unavailable")
        mod = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._registry = mod.ProviderRegistry()

    def complete(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90) -> str:
        self._registry.reload()
        client = self._registry.create_message_client(
            provider=provider,
            model=model,
            options={"timeout_seconds": int(timeout_seconds)},
        )
        return str(client.complete_messages(messages=messages, timeout_seconds=int(timeout_seconds)))

    def stream(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90):
        self._registry.reload()
        client = self._registry.create_message_client(
            provider=provider,
            model=model,
            options={"timeout_seconds": int(timeout_seconds)},
        )
        yield from client.stream_messages(messages=messages, timeout_seconds=int(timeout_seconds))


class ChatService:
    def __init__(
        self,
        literature_search_fn: Callable[[str, int], dict[str, Any]],
        graph_search_fn: Callable[[str, int], list[dict[str, Any]]],
        paper_get_fn: Callable[[str], dict[str, Any] | None],
        variable_get_fn: Callable[[str], dict[str, Any] | None],
    ) -> None:
        self._store = self._build_store()
        self._db_store = self._store if isinstance(self._store, PostgresChatStore) else None
        self._events = EventHub(db_store=self._db_store)
        self._models = ModelRouter()
        self._literature_search = literature_search_fn
        self._graph_search = graph_search_fn
        self._paper_get = paper_get_fn
        self._variable_get = variable_get_fn

    def _build_store(self) -> ChatStore:
        dsn = str(os.getenv("CHAT_STORE_DSN", "")).strip() or str(os.getenv("PIPELINE_JOB_STORE_DSN", "")).strip()
        if dsn:
            try:
                return PostgresChatStore(dsn)
            except Exception:
                return InMemoryChatStore()
        return InMemoryChatStore()

    def create_session(self, title: str = "", default_mode: str = "fast") -> dict[str, Any]:
        mode = "agent" if str(default_mode).strip().lower() == "agent" else "fast"
        return self._store.create_session(title=title, default_mode=mode)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._store.list_sessions()

    def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        sess = self._store.get_session(session_id)
        if sess is None:
            return None
        messages = [self._hydrate_message(m) for m in self._store.list_messages(session_id)]
        return {"session": sess, "messages": messages}

    def submit_message(
        self,
        session_id: str,
        content: str,
        mode: str,
        provider: str,
        model: str,
        stream: bool,
    ) -> dict[str, Any]:
        session = self._store.get_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        now = _now_iso()
        user_msg = {
            "message_id": f"msg_{uuid.uuid4().hex}",
            "session_id": session_id,
            "role": "user",
            "mode": mode,
            "provider": provider,
            "model": model,
            "content": content,
            "citations_json": "[]",
            "retrieval_json": "{}",
            "tool_trace_json": "[]",
            "status": "completed",
            "error_detail": "",
            "created_at": now,
            "updated_at": now,
        }
        self._store.create_message(user_msg)

        assistant_id = f"msg_{uuid.uuid4().hex}"
        assistant_msg = {
            "message_id": assistant_id,
            "session_id": session_id,
            "role": "assistant",
            "mode": mode,
            "provider": provider,
            "model": model,
            "content": "",
            "citations_json": "[]",
            "retrieval_json": "{}",
            "tool_trace_json": "[]",
            "status": "running",
            "error_detail": "",
            "created_at": now,
            "updated_at": now,
        }
        self._store.create_message(assistant_msg)

        t = threading.Thread(
            target=self._run_assistant_message,
            args=(assistant_id, content, mode, provider, model, stream),
            daemon=True,
        )
        t.start()
        return {"user_message_id": user_msg["message_id"], "assistant_message_id": assistant_id}

    def read_events(self, message_id: str, cursor: int, wait_seconds: float = 20.0) -> tuple[list[dict[str, Any]], int, bool]:
        if self._db_store is not None:
            rows = self._db_store.list_events(message_id, after_id=cursor)
            if rows:
                done = any(str(r.get("type")) in {"completed", "failed"} for r in rows)
                next_cursor = int(rows[-1]["event_id"])
                mapped = [{"type": r["type"], "payload": r["payload"], "created_at": r["created_at"]} for r in rows]
                return mapped, next_cursor, done
        return self._events.read_since(message_id=message_id, cursor=cursor, wait_seconds=wait_seconds)

    def _emit(self, message_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._events.publish(message_id, event_type, payload)

    def _run_assistant_message(self, message_id: str, query: str, mode: str, provider: str, model: str, stream: bool) -> None:
        self._emit(message_id, "started", {"message_id": message_id, "mode": mode})
        try:
            if mode == "agent":
                result = self._run_agent(message_id, query, provider, model, stream)
            else:
                result = self._run_fast(message_id, query, provider, model, stream)
            self._store.update_message(
                message_id,
                {
                    "status": "completed",
                    "content": result["answer"],
                    "citations_json": json.dumps(result.get("citations", []), ensure_ascii=False),
                    "retrieval_json": json.dumps(result.get("retrieval_trace", {}), ensure_ascii=False),
                    "tool_trace_json": json.dumps(result.get("tool_trace", []), ensure_ascii=False),
                },
            )
            self._emit(
                message_id,
                "completed",
                {
                    "message_id": message_id,
                    "answer": result["answer"],
                    "citations": result.get("citations", []),
                    "retrieval_trace": result.get("retrieval_trace", {}),
                    "tool_trace": result.get("tool_trace", []),
                },
            )
        except Exception as exc:
            detail = str(exc)
            self._store.update_message(message_id, {"status": "failed", "error_detail": detail})
            self._emit(message_id, "failed", {"message_id": message_id, "error": detail})

    def _rewrite_query(self, query: str, provider: str, model: str) -> str:
        prompt = [
            {"role": "system", "content": "你是检索查询重写助手。输出单行查询，不要解释。"},
            {"role": "user", "content": f"请重写为更适合学术检索的查询：{query}"},
        ]
        try:
            text = self._models.complete(provider=provider, model=model, messages=prompt, timeout_seconds=30).strip()
            return text or query
        except Exception:
            return query

    @staticmethod
    def _build_fallback_citation(query: str) -> dict[str, Any]:
        snippet = str(query or "").strip()[:120]
        return {
            "id": "fallback_fast_no_hit",
            "paper_id": "fallback_fast_no_hit",
            "route": "fallback",
            "title": "未检索到直接证据",
            "text": f"当前知识库未检索到与该问题直接匹配的证据，请谨慎核验。问题：{snippet}",
            "evidence_level": "fallback",
        }

    @staticmethod
    def _build_fast_fallback_answer(query: str, citations: list[dict[str, Any]], reason: str) -> str:
        cite = citations[0] if citations else {}
        title = str(cite.get("title", "检索降级结果") or "检索降级结果")
        text = str(cite.get("text", "") or "").strip()
        q = str(query or "").strip()
        return (
            f"当前模型服务暂时不可用，已按降级策略基于已有证据给出回答。\n"
            f"问题：{q}\n"
            f"结论：请优先参考已检索证据并进行人工核验。\n"
            f"[1] {title}：{text}\n"
            f"降级原因：{reason}"
        ).strip()

    @staticmethod
    def _build_agent_fallback_answer(query: str, observations: list[str], reason: str) -> str:
        q = str(query or "").strip()
        obs = "\n".join(f"- {x}" for x in observations[:3] if str(x or "").strip())
        if not obs:
            obs = "- 暂无可用观察结果"
        return (
            f"当前模型服务暂时不可用，已按 Agent 降级策略返回观察摘要。\n"
            f"问题：{q}\n"
            f"观察摘要：\n{obs}\n"
            f"降级原因：{reason}"
        ).strip()

    def _run_fast(self, message_id: str, query: str, provider: str, model: str, stream: bool) -> dict[str, Any]:
        rewritten = self._rewrite_query(query=query, provider=provider, model=model)
        self._emit(message_id, "citation", {"phase": "query_rewrite", "query": rewritten})

        def _lit_kw() -> list[dict[str, Any]]:
            result = self._literature_search(rewritten, 8)
            return list(result.get("keyword_hits", []))

        def _lit_vec() -> list[dict[str, Any]]:
            result = self._literature_search(rewritten, 8)
            return list(result.get("rag_hits", []))

        def _graph() -> list[dict[str, Any]]:
            return self._graph_search(rewritten, 8)

        retrieval_trace: dict[str, Any] = {"query_original": query, "query_rewritten": rewritten}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            f1 = pool.submit(_lit_kw)
            f2 = pool.submit(_lit_vec)
            f3 = pool.submit(_graph)
            try:
                kw_hits = f1.result(timeout=30)
            except Exception as exc:
                kw_hits = []
                errors.append(f"keyword_failed:{exc}")
            try:
                vec_hits = f2.result(timeout=30)
            except Exception as exc:
                vec_hits = []
                errors.append(f"vector_failed:{exc}")
            try:
                graph_hits = f3.result(timeout=30)
            except Exception as exc:
                graph_hits = []
                errors.append(f"graph_failed:{exc}")

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for route, rows in (("keyword", kw_hits), ("vector", vec_hits), ("graph", graph_hits)):
            for item in rows[:8]:
                key = str(item.get("id", "") or item.get("paper_id", "") or item.get("title", ""))
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append({"route": route, **item})
        merged = merged[:10]
        retrieval_trace["keyword_hits"] = kw_hits
        retrieval_trace["vector_hits"] = vec_hits
        retrieval_trace["graph_hits"] = graph_hits
        retrieval_trace["degraded_routes"] = errors
        citations = merged[:6]
        if not citations:
            fallback = self._build_fallback_citation(query)
            citations = [fallback]
            retrieval_trace["fallback_citation"] = fallback
            self._emit(message_id, "citation", {"phase": "fallback", "citation": fallback})

        evidence_lines: list[str] = []
        for idx, item in enumerate(citations, start=1):
            snippet = str(item.get("text", "") or item.get("title", "") or "")[:240]
            evidence_lines.append(f"[{idx}] route={item.get('route','')} id={item.get('id','')} text={snippet}")
        answer_prompt = [
            {"role": "system", "content": "你是研究问答助手。必须依据证据回答，并用 [编号] 引用。"},
            {"role": "user", "content": f"问题：{query}\n\n检索证据：\n" + "\n".join(evidence_lines)},
        ]
        answer = ""
        try:
            if stream:
                for chunk in self._models.stream(provider=provider, model=model, messages=answer_prompt, timeout_seconds=90):
                    if not chunk:
                        continue
                    answer += chunk
                    self._emit(message_id, "delta", {"text": chunk})
            else:
                answer = self._models.complete(provider=provider, model=model, messages=answer_prompt, timeout_seconds=90)
                if answer:
                    self._emit(message_id, "delta", {"text": answer})
        except Exception as exc:
            reason = str(exc)
            retrieval_trace["model_degraded"] = reason
            self._emit(message_id, "citation", {"phase": "model_degraded", "reason": reason})
            answer = self._build_fast_fallback_answer(query=query, citations=citations, reason=reason)
            self._emit(message_id, "delta", {"text": answer})
        return {
            "answer": answer.strip(),
            "citations": citations,
            "retrieval_trace": retrieval_trace,
            "tool_trace": [],
        }

    def _run_agent(self, message_id: str, query: str, provider: str, model: str, stream: bool) -> dict[str, Any]:
        max_steps = 6
        max_tool_calls = 12
        tool_calls = 0
        tool_trace: list[dict[str, Any]] = []
        observations: list[str] = []

        for step in range(1, max_steps + 1):
            self._emit(message_id, "tool_call", {"phase": "plan", "step": step})
            if step == 1:
                tool_calls += 1
                res = self._literature_search(query, 6)
                merged = list(res.get("merged_hits", []))[:4]
                tool_trace.append({"step": step, "tool": "literature.search", "args": {"query": query, "top_k": 6}, "result_size": len(merged)})
                observations.extend([str(x.get("text", "") or x.get("title", ""))[:200] for x in merged])
                self._emit(message_id, "tool_call", {"phase": "observe", "tool": "literature.search", "step": step, "hits": len(merged)})
            elif step == 2 and tool_calls < max_tool_calls:
                tool_calls += 1
                g = self._graph_search(query, 6)
                tool_trace.append({"step": step, "tool": "graph.search", "args": {"query": query, "limit": 6}, "result_size": len(g)})
                observations.extend([str(x.get("title", "") or x.get("text", "") or "")[:180] for x in g[:3]])
                self._emit(message_id, "tool_call", {"phase": "observe", "tool": "graph.search", "step": step, "hits": len(g)})
            elif step == 3 and tool_calls < max_tool_calls:
                # Try a deep read on the first graph/paper candidate.
                target = None
                for entry in tool_trace:
                    if entry.get("tool") == "graph.search":
                        target = entry
                        break
                if target is not None:
                    tool_calls += 1
                    doc = self._paper_get(str(query))  # fallback no-op for unmatched id
                    if doc is None:
                        doc = {}
                    tool_trace.append({"step": step, "tool": "paper.get", "args": {"paper_id_or_doi": query}, "result_size": 1 if doc else 0})
                    if doc:
                        observations.append(str(doc.get("doi", "") or doc.get("paper_id", "")))
                    self._emit(message_id, "tool_call", {"phase": "observe", "tool": "paper.get", "step": step})
            else:
                self._emit(message_id, "tool_call", {"phase": "reflect", "step": step})
                break

        context = "\n".join(x for x in observations if x)[:4000]
        prompt = [
            {"role": "system", "content": "你是谨慎的 Agent 总结器。基于观察信息直接回答用户问题。"},
            {"role": "user", "content": f"问题：{query}\n\n观察：\n{context}"},
        ]
        answer = ""
        degraded_reason = ""
        try:
            if stream:
                for chunk in self._models.stream(provider=provider, model=model, messages=prompt, timeout_seconds=90):
                    if not chunk:
                        continue
                    answer += chunk
                    self._emit(message_id, "delta", {"text": chunk})
            else:
                answer = self._models.complete(provider=provider, model=model, messages=prompt, timeout_seconds=90)
                if answer:
                    self._emit(message_id, "delta", {"text": answer})
        except Exception as exc:
            degraded_reason = str(exc)
            answer = self._build_agent_fallback_answer(query=query, observations=observations, reason=degraded_reason)
            self._emit(message_id, "delta", {"text": answer})
        citations = [{"id": f"agent_obs_{i+1}", "text": t[:220]} for i, t in enumerate(observations[:5])]
        return {
            "answer": answer.strip(),
            "citations": citations,
            "retrieval_trace": {
                "agent_observations": observations[:8],
                "max_steps": max_steps,
                "max_tool_calls": max_tool_calls,
                "model_degraded": degraded_reason,
            },
            "tool_trace": tool_trace,
        }

    @staticmethod
    def _hydrate_message(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["citations"] = _safe_json(out.get("citations_json", "[]"), [])
        out["retrieval"] = _safe_json(out.get("retrieval_json", "{}"), {})
        out["tool_trace"] = _safe_json(out.get("tool_trace_json", "[]"), [])
        return out

