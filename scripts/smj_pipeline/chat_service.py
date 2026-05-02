from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


def _clip(raw: object, limit: int) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if int(limit) <= 0:
        return text
    if len(text) <= int(limit):
        return text
    return text[: int(limit)] + "..."


def _load_agent_runner_factory_class():
    module_path = Path(__file__).resolve().parent / "agent_runner.py"
    spec = __import__("importlib.util").util.spec_from_file_location(
        "smj_pipeline_agent_runner_for_chat_service",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("agent_runner_unavailable")
    mod = __import__("importlib.util").util.module_from_spec(spec)
    __import__("sys").modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.AgentRunnerFactory


def _load_library_codex_config_module():
    module_path = Path(__file__).resolve().parent / "codex_library_config.py"
    spec = __import__("importlib.util").util.spec_from_file_location(
        "smj_pipeline_codex_library_config_for_chat_service",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("codex_library_config_unavailable")
    mod = __import__("importlib.util").util.module_from_spec(spec)
    __import__("sys").modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ChatStore(Protocol):
    def create_session(self, title: str, default_mode: str, library_id: str) -> dict[str, Any]: ...

    def list_sessions(self, library_id: str) -> list[dict[str, Any]]: ...

    def get_session(self, session_id: str, library_id: str) -> dict[str, Any] | None: ...
    def soft_delete_session(self, session_id: str, deleted_at: str, library_id: str) -> dict[str, Any] | None: ...
    def restore_session(self, session_id: str, library_id: str) -> dict[str, Any] | None: ...

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

    def create_session(self, title: str, default_mode: str, library_id: str) -> dict[str, Any]:
        with self._lock:
            now = _now_iso()
            session_id = f"sess_{uuid.uuid4().hex}"
            row = {
                "session_id": session_id,
                "title": title.strip() or "新会话",
                "default_mode": default_mode,
                "library_id": str(library_id or "").strip(),
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            }
            self._sessions[session_id] = dict(row)
            return dict(row)

    def list_sessions(self, library_id: str) -> list[dict[str, Any]]:
        with self._lock:
            target_library = str(library_id or "").strip()
            rows = list(self._sessions.values())
            rows = [r for r in rows if not str(r.get("deleted_at", "") or "").strip()]
            rows = [r for r in rows if str(r.get("library_id", "") or "").strip() == target_library]
            rows.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
            return [dict(r) for r in rows]

    def get_session(self, session_id: str, library_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(session_id)
            if isinstance(row, dict) and str(row.get("deleted_at", "") or "").strip():
                return None
            if isinstance(row, dict) and str(row.get("library_id", "") or "").strip() != str(library_id or "").strip():
                return None
            return dict(row) if isinstance(row, dict) else None

    def soft_delete_session(self, session_id: str, deleted_at: str, library_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(str(session_id))
            if not isinstance(row, dict):
                return None
            if str(row.get("library_id", "") or "").strip() != str(library_id or "").strip():
                return None
            if str(row.get("deleted_at", "") or "").strip():
                return None
            row["deleted_at"] = str(deleted_at or _now_iso())
            row["updated_at"] = _now_iso()
            return dict(row)

    def restore_session(self, session_id: str, library_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._sessions.get(str(session_id))
            if not isinstance(row, dict):
                return None
            if str(row.get("library_id", "") or "").strip() != str(library_id or "").strip():
                return None
            if not str(row.get("deleted_at", "") or "").strip():
                return None
            row["deleted_at"] = None
            row["updated_at"] = _now_iso()
            return dict(row)

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
            default_mode text not null default 'agent',
            library_id text not null default '',
            created_at timestamptz not null,
            updated_at timestamptz not null,
            deleted_at timestamptz null
        );

        create table if not exists chat_messages (
            message_id text primary key,
            session_id text not null,
            role text not null,
            mode text not null default 'agent',
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
                cur.execute("alter table chat_sessions add column if not exists deleted_at timestamptz null")
                cur.execute("alter table chat_sessions add column if not exists library_id text not null default ''")
            conn.commit()

    def create_session(self, title: str, default_mode: str, library_id: str) -> dict[str, Any]:
        session_id = f"sess_{uuid.uuid4().hex}"
        now = _now_iso()
        row = {
            "session_id": session_id,
            "title": title.strip() or "新会话",
            "default_mode": default_mode,
            "library_id": str(library_id or "").strip(),
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into chat_sessions(session_id, title, default_mode, library_id, created_at, updated_at)
                    values (%(session_id)s, %(title)s, %(default_mode)s, %(library_id)s, %(created_at)s, %(updated_at)s)
                    """,
                    row,
                )
            conn.commit()
        return row

    def list_sessions(self, library_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select session_id, title, default_mode, library_id, created_at, updated_at, deleted_at
                    from chat_sessions
                    where deleted_at is null and library_id=%s
                    order by updated_at desc
                    """,
                    (str(library_id or "").strip(),),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "session_id": row[0],
                    "title": row[1],
                    "default_mode": row[2],
                    "library_id": row[3],
                    "created_at": str(row[4]),
                    "updated_at": str(row[5]),
                    "deleted_at": str(row[6]) if row[6] is not None else None,
                }
            )
        return out

    def get_session(self, session_id: str, library_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select session_id, title, default_mode, library_id, created_at, updated_at, deleted_at "
                    "from chat_sessions where session_id=%s and library_id=%s and deleted_at is null",
                    (session_id, str(library_id or "").strip()),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "title": row[1],
            "default_mode": row[2],
            "library_id": row[3],
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
            "deleted_at": str(row[6]) if row[6] is not None else None,
        }

    def soft_delete_session(self, session_id: str, deleted_at: str, library_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update chat_sessions
                    set deleted_at=%s, updated_at=%s
                    where session_id=%s and library_id=%s and deleted_at is null
                    returning session_id, title, default_mode, library_id, created_at, updated_at, deleted_at
                    """,
                    (str(deleted_at or _now_iso()), _now_iso(), str(session_id), str(library_id or "").strip()),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "title": row[1],
            "default_mode": row[2],
            "library_id": row[3],
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
            "deleted_at": str(row[6]) if row[6] is not None else None,
        }

    def restore_session(self, session_id: str, library_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update chat_sessions
                    set deleted_at=null, updated_at=%s
                    where session_id=%s and library_id=%s and deleted_at is not null
                    returning session_id, title, default_mode, library_id, created_at, updated_at, deleted_at
                    """,
                    (_now_iso(), str(session_id), str(library_id or "").strip()),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "title": row[1],
            "default_mode": row[2],
            "library_id": row[3],
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
            "deleted_at": str(row[6]) if row[6] is not None else None,
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

    def default_provider(self) -> str:
        self._registry.reload()
        return str(self._registry.default_provider or "").strip()


class ChatService:
    def __init__(
        self,
        literature_search_fn: Callable[[str, int], dict[str, Any]],
        graph_search_fn: Callable[[str, int], list[dict[str, Any]]],
        paper_get_fn: Callable[[str], dict[str, Any] | None],
        variable_get_fn: Callable[[str], dict[str, Any] | None],
        library_workspace_resolver_fn: Callable[[str], str] | None = None,
        library_codex_config_resolver_fn: Callable[[str, str], dict[str, Any]] | None = None,
        agent_backend: str | None = None,
    ) -> None:
        self._store = self._build_store()
        self._db_store = self._store if isinstance(self._store, PostgresChatStore) else None
        self._events = EventHub(db_store=self._db_store)
        self._models = ModelRouter()
        self._literature_search = literature_search_fn
        self._graph_search = graph_search_fn
        self._paper_get = paper_get_fn
        self._variable_get = variable_get_fn
        self._library_workspace_resolver = library_workspace_resolver_fn
        self._library_codex_config_resolver = library_codex_config_resolver_fn
        if self._library_codex_config_resolver is None:
            try:
                _lib_cfg_mod = _load_library_codex_config_module()
                self._library_codex_config_resolver = (
                    lambda workspace_path, library_id: _lib_cfg_mod.load_or_init_library_codex_config(
                        workspace_path=workspace_path,
                        library_id=library_id,
                    )
                )
            except Exception:
                self._library_codex_config_resolver = None
        self._agent_backend = str(agent_backend or os.getenv("CHAT_AGENT_BACKEND", "codex")).strip().lower() or "codex"
        factory_cls = _load_agent_runner_factory_class()
        config_path = Path(os.getenv("CHAT_CODEX_CONFIG_PATH", "outputs/chat/codex_runner_config.json") or "outputs/chat/codex_runner_config.json")
        self._runner_factory = factory_cls(codex_config_path=config_path)
        self._restore_deadline_by_session: dict[str, float] = {}

    def _build_store(self) -> ChatStore:
        dsn = str(os.getenv("CHAT_STORE_DSN", "")).strip() or str(os.getenv("PIPELINE_JOB_STORE_DSN", "")).strip()
        if dsn:
            try:
                return PostgresChatStore(dsn)
            except Exception:
                return InMemoryChatStore()
        return InMemoryChatStore()

    def create_session(self, title: str = "", default_mode: str = "agent", library_id: str = "") -> dict[str, Any]:
        _ = default_mode
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if self._agent_backend == "codex":
            workspace = self._resolve_workspace_path(lib)
            runner = self._runner_factory.build("codex")
            thread_res = runner.thread_start(
                workdir=workspace,
                library_id=lib,
                runtime_overrides=self._build_codex_runtime_overrides(workspace, lib),
            )
            thread = thread_res.get("thread") if isinstance(thread_res.get("thread"), dict) else {}
            thread_id = str(thread.get("id", "") or "").strip()
            if not thread_id:
                raise RuntimeError("codex_thread_start_failed")
            title_text = str(title or "").strip()
            if title_text:
                try:
                    runner.thread_set_name(
                        thread_id=thread_id,
                        name=title_text,
                        workdir=workspace,
                        runtime_overrides=self._build_codex_runtime_overrides(workspace, lib),
                    )
                except Exception:
                    pass
            now = _now_iso()
            return {
                "session_id": thread_id,
                "title": str(title_text or thread.get("name", "") or f"Session {thread_id[:8]}"),
                "default_mode": "agent",
                "library_id": lib,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
                "source": "codex",
            }
        return self._store.create_session(title=title, default_mode="agent", library_id=lib)

    def list_sessions(self, library_id: str = "") -> list[dict[str, Any]]:
        self._cleanup_restore_deadlines()
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if self._agent_backend == "codex":
            workspace = self._resolve_workspace_path(lib)
            runner = self._runner_factory.build("codex")
            list_res = runner.thread_list(
                workdir=workspace,
                archived=False,
                limit=200,
                runtime_overrides=self._build_codex_runtime_overrides(workspace, lib),
            )
            rows = list_res.get("data") if isinstance(list_res.get("data"), list) else []
            out: list[dict[str, Any]] = []
            seen_session_ids: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sid = str(row.get("id", "") or "").strip()
                if not sid:
                    continue
                if sid in seen_session_ids:
                    continue
                seen_session_ids.add(sid)
                goal_obj = row.get("goal")
                goal_text = ""
                if isinstance(goal_obj, dict):
                    goal_text = str(goal_obj.get("text", "") or goal_obj.get("goal", "") or "").strip()
                elif isinstance(goal_obj, str):
                    goal_text = goal_obj.strip()
                title_text = str(row.get("name", "") or "").strip() or goal_text
                if not title_text:
                    msg_rows = self._store.list_messages(sid)
                    first_user = next((m for m in msg_rows if str(m.get("role", "")) == "user"), None)
                    if isinstance(first_user, dict):
                        title_text = str(first_user.get("content", "") or "").strip()
                if not title_text:
                    title_text = f"Session {sid[:8]}"
                out.append(
                    {
                        "session_id": sid,
                        "title": title_text,
                        "default_mode": "agent",
                        "library_id": lib,
                        "created_at": str(row.get("createdAt", "") or row.get("created_at", "") or ""),
                        "updated_at": str(row.get("updatedAt", "") or row.get("updated_at", "") or ""),
                        "deleted_at": None,
                        "source": "codex",
                    }
                )
            return out
        return self._store.list_sessions(library_id=lib)

    def delete_session(self, session_id: str, undo_window_seconds: int = 5, library_id: str = "") -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if self._agent_backend == "codex":
            workspace = self._resolve_workspace_path(lib)
            runner = self._runner_factory.build("codex")
            runner.thread_archive(
                thread_id=str(session_id),
                workdir=workspace,
                runtime_overrides=self._build_codex_runtime_overrides(workspace, lib),
            )
            now = datetime.now(timezone.utc)
            return {
                "session_id": str(session_id),
                "library_id": lib,
                "deleted_at": now.isoformat(),
                "undo_window_seconds": int(max(1, undo_window_seconds)),
                "undo_deadline": (now + timedelta(seconds=max(1, int(undo_window_seconds)))).isoformat(),
                "source": "codex",
            }
        sess = self._store.get_session(session_id, library_id=lib)
        if sess is None:
            raise KeyError("session_not_found")
        now = datetime.now(timezone.utc)
        deleted = self._store.soft_delete_session(session_id=session_id, deleted_at=now.isoformat(), library_id=lib)
        if deleted is None:
            raise KeyError("session_not_found")
        window = max(1, int(undo_window_seconds))
        deadline = now + timedelta(seconds=window)
        self._restore_deadline_by_session[f"{lib}:{str(session_id)}"] = deadline.timestamp()
        return {
            "session_id": str(session_id),
            "library_id": lib,
            "deleted_at": now.isoformat(),
            "undo_window_seconds": window,
            "undo_deadline": deadline.isoformat(),
        }

    def restore_session(self, session_id: str, library_id: str = "") -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if self._agent_backend == "codex":
            workspace = self._resolve_workspace_path(lib)
            runner = self._runner_factory.build("codex")
            runner.thread_unarchive(
                thread_id=str(session_id),
                workdir=workspace,
                runtime_overrides=self._build_codex_runtime_overrides(workspace, lib),
            )
            return {"session_id": str(session_id), "library_id": lib, "restored": True, "source": "codex"}
        self._cleanup_restore_deadlines()
        restore_key = f"{lib}:{str(session_id)}"
        deadline_ts = self._restore_deadline_by_session.get(restore_key)
        if deadline_ts is None:
            return {"session_id": str(session_id), "library_id": lib, "restored": False, "error": "restore_window_expired"}
        if time.time() > float(deadline_ts):
            self._restore_deadline_by_session.pop(restore_key, None)
            return {"session_id": str(session_id), "library_id": lib, "restored": False, "error": "restore_window_expired"}
        restored = self._store.restore_session(session_id=session_id, library_id=lib)
        if restored is None:
            return {"session_id": str(session_id), "library_id": lib, "restored": False, "error": "session_not_found"}
        self._restore_deadline_by_session.pop(restore_key, None)
        return {"session_id": str(session_id), "library_id": lib, "restored": True}

    def _cleanup_restore_deadlines(self) -> None:
        now_ts = time.time()
        expired = [sid for sid, ts in self._restore_deadline_by_session.items() if now_ts > float(ts)]
        for sid in expired:
            self._restore_deadline_by_session.pop(sid, None)

    def get_session_with_messages(self, session_id: str, library_id: str = "") -> dict[str, Any] | None:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        if self._agent_backend == "codex":
            rows = self.list_sessions(library_id=lib)
            matched = next((r for r in rows if str(r.get("session_id", "")) == str(session_id)), None)
            if not isinstance(matched, dict):
                matched = {
                    "session_id": str(session_id),
                    "title": "New chat",
                    "default_mode": "agent",
                    "library_id": lib,
                    "created_at": "",
                    "updated_at": "",
                    "deleted_at": None,
                    "source": "codex",
                }
            local_messages = [self._hydrate_message(m) for m in self._store.list_messages(str(session_id))]
            return {"session": matched, "messages": local_messages}
        sess = self._store.get_session(session_id, library_id=lib)
        if sess is None:
            return None
        messages = [self._hydrate_message(m) for m in self._store.list_messages(session_id)]
        return {"session": sess, "messages": messages}

    def _build_codex_runtime_overrides(self, workspace: str, library_id: str) -> dict[str, Any]:
        runtime_overrides: dict[str, Any] = {}
        if callable(self._library_codex_config_resolver):
            try:
                lib_cfg = self._library_codex_config_resolver(workspace, str(library_id or "").strip())
            except Exception:
                lib_cfg = {}
            if isinstance(lib_cfg, dict):
                runtime_overrides = {
                    "codex_home": str(lib_cfg.get("codex_home", "") or "").strip(),
                    "mcp_servers": lib_cfg.get("mcp_servers", []),
                    "project_skills": lib_cfg.get("project_skills", []),
                }
        return runtime_overrides

    def submit_message(
        self,
        session_id: str,
        content: str,
        mode: str,
        provider: str,
        model: str,
        stream: bool,
        library_id: str = "",
    ) -> dict[str, Any]:
        lib = str(library_id or "").strip()
        if not lib:
            raise ValueError("library_id_required")
        session = self._store.get_session(session_id, library_id=lib)
        if session is None and self._agent_backend != "codex":
            raise KeyError("session_not_found")
        if session is None:
            session = {"session_id": session_id, "default_mode": "agent", "library_id": lib}
        now = _now_iso()
        normalized_mode = str(mode or session.get("default_mode", "agent") or "agent").strip().lower()
        if normalized_mode not in {"agent", "fast"}:
            normalized_mode = "agent"
        user_msg = {
            "message_id": f"msg_{uuid.uuid4().hex}",
            "session_id": session_id,
            "role": "user",
            "mode": normalized_mode,
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
            "mode": normalized_mode,
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
            args=(assistant_id, content, normalized_mode, provider, model, stream, lib, session_id),
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

    def _run_assistant_message(
        self,
        message_id: str,
        query: str,
        mode: str,
        provider: str,
        model: str,
        stream: bool,
        library_id: str = "",
        session_id: str = "",
    ) -> None:
        normalized_mode = str(mode or "agent").strip().lower()
        if normalized_mode not in {"agent", "fast"}:
            normalized_mode = "agent"
        self._emit(message_id, "started", {"message_id": message_id, "mode": normalized_mode})
        self._emit(message_id, "status", {"stage": "retrieve", "label": "正在规划工具调用"})
        try:
            if normalized_mode == "fast":
                result = self._run_fast(message_id, query, provider, model, stream, library_id=library_id)
            else:
                result = self._run_agent(message_id, query, provider, model, stream, library_id=library_id, thread_id=session_id)
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
            self._emit(message_id, "status", {"stage": "done", "label": "完成", "state": "completed"})
        except Exception as exc:
            detail = str(exc)
            error_code = self._extract_error_code(detail)
            backend = self._extract_backend(detail)
            self._store.update_message(message_id, {"status": "failed", "error_detail": detail})
            self._emit(
                message_id,
                "failed",
                {
                    "message_id": message_id,
                    "error": detail,
                    "error_code": error_code,
                    "backend": backend,
                    "library_id": str(library_id or "").strip(),
                },
            )
            self._emit(message_id, "status", {"stage": "done", "label": "失败", "state": "failed"})

    @staticmethod
    def _extract_error_code(detail: str) -> str:
        text = str(detail or "").strip()
        if not text:
            return "unknown_error"
        return text.split(":", 1)[0] if ":" in text else text

    @staticmethod
    def _extract_backend(detail: str) -> str:
        text = str(detail or "").strip()
        if text.startswith("agent_backend_unavailable:"):
            return text.split(":", 1)[1].strip()
        if text.startswith("codex_"):
            return "codex"
        if text.startswith("hermes_"):
            return "hermes"
        return ""

    def _call_literature_search(self, query: str, top_k: int, library_id: str = "") -> dict[str, Any]:
        try:
            return self._literature_search(query, top_k, library_id)  # type: ignore[misc]
        except TypeError:
            return self._literature_search(query, top_k)

    @staticmethod
    def _extract_paragraph_text(hit: dict[str, Any]) -> str:
        context = hit.get("context", {}) if isinstance(hit.get("context"), dict) else {}
        paragraph = context.get("paragraph", {}) if isinstance(context.get("paragraph"), dict) else {}
        paragraph_text = str(paragraph.get("text", "") or "").strip()
        if paragraph_text:
            return paragraph_text
        level = str(hit.get("level", "") or "").strip().lower()
        if level == "paragraph":
            return str(hit.get("text", "") or "").strip()
        return ""

    def _collect_paragraph_evidence(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        out: list[dict[str, Any]] = []
        seen_texts: set[str] = set()
        dropped = 0
        for item in rows:
            paragraph_text = self._extract_paragraph_text(item if isinstance(item, dict) else {})
            if not paragraph_text:
                dropped += 1
                continue
            norm = " ".join(paragraph_text.split())
            if not norm or norm in seen_texts:
                continue
            seen_texts.add(norm)
            row = dict(item)
            row["text"] = paragraph_text
            out.append(row)
        return out, dropped

    def _emit_tool_call(
        self,
        message_id: str,
        backend: str,
        step_id: str,
        state: str,
        summary: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "backend": backend,
            "step_id": step_id,
            "state": state,
            "summary": summary,
            "timestamp": _now_iso(),
            "kind": "tool",
            "event": "tool_call",
        }
        if isinstance(extra, dict):
            payload.update(extra)
        self._emit(message_id, "tool_call", payload)

    def _emit_agent_item(self, message_id: str, event_name: str, payload: dict[str, Any]) -> None:
        row = dict(payload)
        row.setdefault("timestamp", _now_iso())
        row.setdefault("event", str(event_name or "").strip())
        row.setdefault("kind", "agent_item")
        self._emit(message_id, event_name, row)

    def _resolve_workspace_path(self, library_id: str) -> str:
        lib = str(library_id or "").strip()
        if not callable(self._library_workspace_resolver):
            raise RuntimeError("codex_workspace_resolver_unavailable")
        resolved = str(self._library_workspace_resolver(lib) or "").strip()
        if not resolved:
            raise RuntimeError(f"codex_workspace_path_missing:library_id={lib}")
        path = Path(resolved).resolve()
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"codex_workspace_path_invalid:library_id={lib}:path={path}")
        return str(path)

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

    def _run_fast(
        self,
        message_id: str,
        query: str,
        provider: str,
        model: str,
        stream: bool,
        library_id: str = "",
    ) -> dict[str, Any]:
        if not str(library_id or "").strip():
            raise RuntimeError("library_id_required")
        effective_provider = str(provider or "").strip()
        effective_model = str(model or "").strip()
        if effective_provider.lower() == "codex":
            fallback_provider = self._models.default_provider()
            if fallback_provider:
                effective_provider = fallback_provider
                effective_model = ""
                self._emit(
                    message_id,
                    "citation",
                    {
                        "phase": "provider_fallback",
                        "from": str(provider or "").strip(),
                        "to": effective_provider,
                    },
                )

        rewritten = self._rewrite_query(query=query, provider=effective_provider, model=effective_model)
        self._emit(message_id, "citation", {"phase": "query_rewrite", "query": rewritten})
        self._emit(message_id, "status", {"stage": "retrieve", "label": "正在召回相关片段"})
        library = str(library_id or "").strip()

        def _lit_kw() -> list[dict[str, Any]]:
            result = self._call_literature_search(rewritten, 8, library)
            return list(result.get("keyword_hits", []))

        def _lit_vec() -> list[dict[str, Any]]:
            result = self._call_literature_search(rewritten, 8, library)
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

        tool_trace: list[dict[str, Any]] = [
            {
                "backend": "builtin",
                "step": 1,
                "state": "completed",
                "kind": "tool",
                "tool": "rag_search.keyword",
                "args": {"query": rewritten, "top_k": 8, "library_id": library, "route": "keyword"},
                "summary": "rag_search.keyword",
                "result": {"hit_count": len(kw_hits), "sample_ids": [str(x.get("id", "") or x.get("paper_id", "")) for x in kw_hits[:3]]},
            },
            {
                "backend": "builtin",
                "step": 2,
                "state": "completed",
                "kind": "tool",
                "tool": "rag_search.vector",
                "args": {"query": rewritten, "top_k": 8, "library_id": library, "route": "vector"},
                "summary": "rag_search.vector",
                "result": {"hit_count": len(vec_hits), "sample_ids": [str(x.get("id", "") or x.get("paper_id", "")) for x in vec_hits[:3]]},
            },
            {
                "backend": "builtin",
                "step": 3,
                "state": "completed",
                "kind": "tool",
                "tool": "graph_search",
                "args": {"query": rewritten, "limit": 8, "library_id": library},
                "summary": "graph_search",
                "result": {"hit_count": len(graph_hits), "sample_ids": [str(x.get("id", "") or x.get("paper_id", "")) for x in graph_hits[:3]]},
            },
        ]

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
        paragraph_hits, dropped_non_paragraph_count = self._collect_paragraph_evidence(merged[:10])
        retrieval_trace["paragraph_context_applied"] = True
        retrieval_trace["dropped_non_paragraph_count"] = dropped_non_paragraph_count
        retrieval_trace["library_id"] = library
        if not paragraph_hits:
            raise RuntimeError("paragraph_context_unavailable")
        citations = paragraph_hits[:6]

        evidence_lines: list[str] = []
        for idx, item in enumerate(citations, start=1):
            snippet = str(item.get("text", "") or item.get("title", "") or "")[:240]
            evidence_lines.append(f"[{idx}] route={item.get('route','')} id={item.get('id','')} text={snippet}")
        answer_prompt = [
            {"role": "system", "content": "你是研究问答助手。必须依据证据回答，并用 [编号] 引用。"},
            {"role": "user", "content": f"问题：{query}\n\n检索证据：\n" + "\n".join(evidence_lines)},
        ]
        answer = ""
        self._emit(message_id, "status", {"stage": "generate", "label": "正在生成回答"})
        try:
            if stream:
                for chunk in self._models.stream(provider=effective_provider, model=effective_model, messages=answer_prompt, timeout_seconds=90):
                    if not chunk:
                        continue
                    answer += chunk
                    self._emit(message_id, "delta", {"text": chunk})
            else:
                answer = self._models.complete(provider=effective_provider, model=effective_model, messages=answer_prompt, timeout_seconds=90)
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
            "tool_trace": tool_trace,
        }

    def _run_agent(
        self,
        message_id: str,
        query: str,
        provider: str,
        model: str,
        stream: bool,
        library_id: str = "",
        thread_id: str = "",
    ) -> dict[str, Any]:
        _ = provider, model
        if not str(library_id or "").strip():
            raise RuntimeError("library_id_required")
        backend = self._agent_backend
        if backend == "hermes":
            runner = self._runner_factory.build("hermes")
            _ = runner
            raise RuntimeError("agent_backend_unavailable:hermes")
        if backend != "codex":
            raise RuntimeError(f"agent_backend_invalid:{backend}")

        workspace = self._resolve_workspace_path(library_id)
        runner = self._runner_factory.build("codex")
        self._emit(message_id, "status", {"stage": "retrieve", "label": "正在由 Codex 进行工具调用与分析"})

        tool_trace: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        answer_parts: list[str] = []
        final_answer = ""
        step_no = 0
        rag_hits_seen = 0
        rag_error_reason = ""
        rag_tool_called = False

        runtime_overrides = self._build_codex_runtime_overrides(workspace, str(library_id or "").strip())

        def _item_id(item: dict[str, Any], fallback_prefix: str = "item") -> str:
            raw = str(item.get("id", "") or "").strip()
            if raw:
                return raw
            return f"{fallback_prefix}-{uuid.uuid4().hex[:8]}"

        def _on_app_event(msg: dict[str, Any]) -> None:
            nonlocal step_no, final_answer, rag_hits_seen, rag_error_reason, rag_tool_called
            method = str(msg.get("method", "") or "")
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

            if method == "item/started":
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                item_type = str(item.get("type", "") or "")
                step_no += 1
                step_id = _item_id(item, "started")
                item_tool = str(item.get("tool", "") or "").strip()
                item_cmd = str(item.get("command", "") or "").strip()
                summary = item_tool or item_cmd or item_type or "item_started"
                self._emit_agent_item(
                    message_id,
                    "agent_item_started",
                    {
                        "backend": "codex",
                        "step_id": step_id,
                        "item": item_type or "unknown",
                        "state": "started",
                        "kind": "agent_item",
                        "summary": summary,
                        "detail": _clip(json.dumps(item, ensure_ascii=False), 640),
                    },
                )
                if item_type in {"mcpToolCall", "commandExecution", "fileChange"}:
                    label = summary
                    kind = "tool" if item_type == "mcpToolCall" else ("command" if item_type == "commandExecution" else "file_change")
                    self._emit_tool_call(
                        message_id,
                        "codex",
                        step_id,
                        "started",
                        label,
                        {
                            "tool": label,
                            "backend": "codex",
                            "kind": kind,
                            "args_preview": _clip(json.dumps(item.get("arguments", {}), ensure_ascii=False), 260),
                            "detail": _clip(json.dumps(item, ensure_ascii=False), 640),
                        },
                    )
                return

            if method == "item/agentMessage/delta":
                delta = str(params.get("delta", "") or "")
                if not delta:
                    return
                answer_parts.append(delta)
                if stream:
                    self._emit(message_id, "delta", {"text": delta})
                self._emit_agent_item(
                    message_id,
                    "agent_item_delta",
                    {
                        "backend": "codex",
                        "step_id": "agent-message",
                        "kind": "message",
                        "state": "streaming",
                        "text": delta[:1000],
                        "summary": _clip(delta, 220),
                    },
                )
                return

            if method == "item/completed":
                item = params.get("item") if isinstance(params.get("item"), dict) else {}
                item_type = str(item.get("type", "") or "")
                step_id = _item_id(item, "completed")

                if item_type == "agentMessage":
                    text = str(item.get("text", "") or "").strip()
                    if text:
                        final_answer = text
                    self._emit_agent_item(
                        message_id,
                        "agent_item_completed",
                        {
                            "backend": "codex",
                            "step_id": step_id,
                            "item": "agentMessage",
                            "kind": "message",
                            "state": "completed",
                            "summary": _clip(text, 220) or "message_completed",
                        },
                    )
                    return

                if item_type in {"mcpToolCall", "mcp_tool_call"} or bool(item.get("tool")):
                    server = str(item.get("server", "") or "")
                    tool = str(item.get("tool", "") or "")
                    status = str(item.get("status", "") or "completed")
                    arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                    result = item.get("result") if isinstance(item.get("result"), dict) else {}
                    output = item.get("output") if isinstance(item.get("output"), dict) else {}
                    structured = (
                        result.get("structuredContent")
                        if isinstance(result.get("structuredContent"), dict)
                        else (
                            result.get("structured_content")
                            if isinstance(result.get("structured_content"), dict)
                            else (
                                output.get("structuredContent")
                                if isinstance(output.get("structuredContent"), dict)
                                else {}
                            )
                        )
                    )
                    summary = f"{server}:{tool}" if server else tool
                    tool_norm = tool.split(".")[-1].strip().lower()

                    if not structured:
                        content_obj = result.get("content")
                        content_rows = content_obj if isinstance(content_obj, list) else []
                        if content_rows:
                            first = content_rows[0] if isinstance(content_rows[0], dict) else {}
                            first_text = str(first.get("text", "") or "").strip()
                            if first_text.startswith("{") and first_text.endswith("}"):
                                parsed = _safe_json(first_text, {})
                                if isinstance(parsed, dict):
                                    structured = parsed

                    if tool_norm == "rag_search":
                        rag_tool_called = True
                        if bool(result.get("isError")) and not rag_error_reason:
                            rag_error_reason = str(structured.get("error", "") or summary or "rag_search_error")
                        paragraph_hits = structured.get("paragraph_hits") if isinstance(structured.get("paragraph_hits"), list) else []
                        rag_hits_seen += len(paragraph_hits)
                        for hit in paragraph_hits[:8]:
                            if not isinstance(hit, dict):
                                continue
                            text = str(hit.get("text", "") or "").strip()
                            if not text:
                                continue
                            citations.append(
                                {
                                    "id": str(hit.get("id", "") or hit.get("paper_id", "") or f"rag_{len(citations)+1}"),
                                    "title": str(hit.get("title", "") or ""),
                                    "text": text,
                                    "context": {"paragraph": {"text": text}},
                                }
                            )

                    output_summary = _clip(json.dumps(result.get("content", "") or structured, ensure_ascii=False), 240)
                    args_preview = _clip(json.dumps(arguments, ensure_ascii=False), 240)
                    detail_text = _clip(json.dumps({"arguments": arguments, "result": result, "output": output}, ensure_ascii=False), 900)
                    trace_row = {
                        "backend": "codex",
                        "step": len(tool_trace) + 1,
                        "step_id": step_id,
                        "state": "completed" if status in {"completed", "ok", "success"} else "failed",
                        "kind": "tool",
                        "tool": tool or "mcpToolCall",
                        "args": arguments,
                        "summary": summary,
                        "args_preview": args_preview,
                        "output_summary": output_summary,
                        "detail": detail_text,
                        "raw": {"arguments": arguments, "result": result, "output": output},
                    }
                    tool_trace.append(trace_row)
                    self._emit_tool_call(
                        message_id,
                        "codex",
                        step_id,
                        trace_row["state"],
                        summary,
                        {
                            "tool": trace_row["tool"],
                            "backend": "codex",
                            "kind": "tool",
                            "summary": summary,
                            "state": trace_row["state"],
                            "step_id": step_id,
                            "args_preview": args_preview,
                            "output_summary": output_summary,
                            "detail": detail_text,
                            "raw": {"arguments": arguments, "result": result, "output": output},
                        },
                    )
                    self._emit_agent_item(
                        message_id,
                        "agent_item_completed",
                        {
                            "backend": "codex",
                            "step_id": step_id,
                            "item": "mcpToolCall",
                            "kind": "tool",
                            "state": trace_row["state"],
                            "summary": summary,
                            "detail": output_summary,
                        },
                    )
                    return

                self._emit_agent_item(
                    message_id,
                    "agent_item_completed",
                    {
                        "backend": "codex",
                        "step_id": step_id,
                        "item": item_type or "unknown",
                        "kind": "agent_item",
                        "state": "completed",
                        "summary": "completed",
                    },
                )
                return

            if method == "mcpServer/startupStatus/updated":
                name = str(params.get("name", "") or "")
                status = str(params.get("status", "") or "")
                error = str(params.get("error", "") or "")
                detail = f"{name}:{status}" if name else status
                if error:
                    detail = f"{detail}:{error}" if detail else error
                self._emit_tool_call(
                    message_id,
                    "codex",
                    f"mcp-{len(tool_trace)+1}",
                    "completed" if status == "ready" else "started",
                    "mcp.startup",
                    {
                        "backend": "codex",
                        "kind": "system",
                        "summary": detail,
                        "state": status,
                        "detail": detail,
                    },
                )
                return

        try:
            agent_timeout_seconds = int(os.getenv("CHAT_AGENT_TURN_TIMEOUT_SECONDS", "180") or "180")
            if agent_timeout_seconds < 30:
                agent_timeout_seconds = 30
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(
                    runner.run_turn,
                    query=query,
                    workdir=workspace,
                    library_id=library_id,
                    thread_id=str(thread_id or "").strip(),
                    runtime_overrides=runtime_overrides,
                    on_event=_on_app_event,
                )
                result = fut.result(timeout=agent_timeout_seconds)
        except Exception as exc:
            self._emit(message_id, "citation", {"phase": "agent_degraded", "reason": str(exc)})
            degraded = self._run_fast(
                message_id=message_id,
                query=query,
                provider=provider,
                model=model,
                stream=stream,
                library_id=library_id,
            )
            out_trace = list(tool_trace)
            out_trace.append(
                {
                    "backend": "codex",
                    "step": len(out_trace) + 1,
                    "state": "failed",
                    "kind": "tool",
                    "tool": "codex.run_turn",
                    "args": {"library_id": library_id},
                    "summary": "codex.run_turn timeout/failure",
                    "result": {"error": str(exc)},
                }
            )
            out_trace.extend(list(degraded.get("tool_trace", [])))
            retrieval_trace = degraded.get("retrieval_trace", {}) if isinstance(degraded.get("retrieval_trace"), dict) else {}
            retrieval_trace["backend"] = "codex_degraded_to_fast"
            retrieval_trace["degraded_reason"] = str(exc)
            return {
                "answer": str(degraded.get("answer", "") or "").strip(),
                "citations": list(degraded.get("citations", []) or []),
                "retrieval_trace": retrieval_trace,
                "tool_trace": out_trace,
            }
        self._emit(message_id, "status", {"stage": "generate", "label": "正在由 Codex 生成回答"})

        answer = str(result.get("answer", "") or "").strip()
        if not answer:
            answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("agent_backend_unavailable:codex:empty_output")

        if not stream:
            self._emit(message_id, "delta", {"text": answer})
        elif not answer_parts:
            self._emit(message_id, "delta", {"text": answer})

        def _is_smalltalk(raw_query: str) -> bool:
            text = str(raw_query or "").strip().lower()
            if not text or len(text) > 24:
                return False
            simple_hits = (
                "hi",
                "hello",
                "hey",
                "你好",
                "您好",
                "嗨",
                "在吗",
                "在么",
                "早上好",
                "下午好",
                "晚上好",
            )
            return any(token in text for token in simple_hits)

        if not citations:
            return {
                "answer": answer,
                "citations": [],
                "retrieval_trace": {
                    "backend": "codex",
                    "library_id": str(library_id or "").strip(),
                    "workspace_path": workspace,
                    "paragraph_context_applied": False,
                    "smalltalk_bypass": _is_smalltalk(query),
                    "rag_tool_called": bool(rag_tool_called),
                    "rag_hits_seen": rag_hits_seen,
                    "rag_error_reason": rag_error_reason,
                    "thread_id": str(result.get("thread_id", "") or ""),
                    "turn_id": str(result.get("turn_id", "") or ""),
                },
                "tool_trace": tool_trace,
            }

        return {
            "answer": answer,
            "citations": citations[:8],
            "retrieval_trace": {
                "backend": "codex",
                "library_id": str(library_id or "").strip(),
                "workspace_path": workspace,
                "paragraph_context_applied": True,
                "dropped_non_paragraph_count": 0,
                "rag_hits_seen": rag_hits_seen,
                "thread_id": str(result.get("thread_id", "") or ""),
                "turn_id": str(result.get("turn_id", "") or ""),
            },
            "tool_trace": tool_trace,
        }

    @staticmethod
    def _hydrate_message(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["citations"] = _safe_json(out.get("citations_json", "[]"), [])
        out["retrieval"] = _safe_json(out.get("retrieval_json", "{}"), {})
        out["tool_trace"] = _safe_json(out.get("tool_trace_json", "[]"), [])
        detail = str(out.get("error_detail", "") or "").strip()
        out["error_code"] = ChatService._extract_error_code(detail) if detail else ""
        out["error_backend"] = ChatService._extract_backend(detail) if detail else ""
        return out

