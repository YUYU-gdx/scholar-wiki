from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
import uuid

from kn_graph.config import Settings

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class _InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item = dict(payload)
            self._jobs[item["job_id"]] = item
            return dict(item)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            return dict(item) if isinstance(item, dict) else None

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            current = self._jobs[job_id]
            current_status = _norm_status(current.get("status"))
            payload = dict(updates)
            next_status = _norm_status(payload.get("status")) if "status" in payload else ""
            if current_status in TERMINAL_JOB_STATUSES:
                if not next_status:
                    return dict(current)
                if next_status != current_status:
                    return dict(current)
            current.update(payload)
            current["updated_at"] = _now_iso()
            return dict(current)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        return self.update_job(job_id, {"requested_cancel": True})

    def list_jobs(
        self,
        *,
        library_id: str = "",
        status: str = "",
        query: str = "",
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        lib = str(library_id or "").strip()
        st = str(status or "").strip().lower()
        q = str(query or "").strip().lower()
        with self._lock:
            rows = [dict(v) for v in self._jobs.values()]
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if lib and str(row.get("library_id", "") or "").strip() != lib:
                continue
            if st and str(row.get("status", "") or "").strip().lower() != st:
                continue
            if q:
                hay = " ".join([
                    str(row.get("job_id", "") or ""),
                    str(row.get("library_id", "") or ""),
                    str(row.get("file_name", "") or ""),
                    str(row.get("input_path", "") or ""),
                    str(row.get("error_detail", "") or ""),
                ]).lower()
                if q not in hay:
                    continue
            filtered.append(row)
        reverse = sort != "created_at_asc"
        filtered.sort(key=lambda x: str(x.get("created_at", "") or ""), reverse=reverse)
        total = len(filtered)
        start = max(0, (max(1, int(page)) - 1) * max(1, int(page_size)))
        end = start + max(1, int(page_size))
        return filtered[start:end], total

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    # Stage task APIs are SQLite-first for production use.
    # In-memory store keeps no-op compatibility for tests that do not use stage pools.
    def enqueue_stage_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("id", f"task_{uuid.uuid4().hex}")
        item.setdefault("status", "queued")
        item.setdefault("created_at", _now_iso())
        item.setdefault("updated_at", item["created_at"])
        return item

    def claim_stage_task(self, stage: str, worker_id: str, lease_seconds: int = 120, extract_limit: int = 3) -> dict[str, Any] | None:
        return None

    def heartbeat_stage_task(self, task_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
        return False

    def complete_stage_task(self, task_id: str, worker_id: str, output_json: dict[str, Any] | None = None) -> bool:
        return False

    def fail_stage_task(
        self,
        task_id: str,
        worker_id: str,
        error_code: str,
        error_detail: str,
        *,
        retryable: bool,
        backoff_seconds: int = 0,
    ) -> bool:
        return False

    def list_stage_tasks(self, job_id: str) -> list[dict[str, Any]]:
        return []


class _SQLiteJobStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        ddl = """
        create table if not exists pipeline_jobs (
            job_id text primary key,
            status text not null,
            stage text not null,
            progress integer not null,
            error_code text not null default '',
            error_detail text not null default '',
            input_path text not null default '',
            output_path text not null default '',
            options_json text not null default '{}',
            result_json text not null default '{}',
            requested_cancel integer not null default 0,
            idempotency_key text not null default '',
            last_event text not null default 'accepted',
            created_at text not null,
            updated_at text not null,
            file_size integer not null default 0,
            file_hash text not null default '',
            library_id text not null default '',
            workspace_path text not null default '',
            source_job_id text not null default '',
            file_name text not null default ''
        );
        create index if not exists idx_pipeline_jobs_updated_at on pipeline_jobs(updated_at);
        create index if not exists idx_pipeline_jobs_created_at on pipeline_jobs(created_at);
        create index if not exists idx_pipeline_jobs_library_id on pipeline_jobs(library_id);
        create unique index if not exists idx_pipeline_jobs_idempotency on pipeline_jobs(idempotency_key) where idempotency_key <> '';

        create table if not exists pipeline_stage_tasks (
            id text primary key,
            job_id text not null,
            stage text not null,
            status text not null,
            priority integer not null default 100,
            attempt integer not null default 0,
            max_attempts integer not null default 3,
            worker_id text not null default '',
            lease_until text not null default '',
            heartbeat_at text not null default '',
            idempotency_key text not null,
            depends_on_task_id text not null default '',
            input_json text not null default '{}',
            output_json text not null default '{}',
            error_code text not null default '',
            error_detail text not null default '',
            created_at text not null,
            updated_at text not null
        );
        create unique index if not exists idx_stage_tasks_job_stage on pipeline_stage_tasks(job_id, stage);
        create unique index if not exists idx_stage_tasks_idempotency on pipeline_stage_tasks(idempotency_key);
        create index if not exists idx_stage_tasks_lookup on pipeline_stage_tasks(stage, status, priority, created_at);
        create index if not exists idx_stage_tasks_lease on pipeline_stage_tasks(status, lease_until);

        create table if not exists pipeline_task_events (
            id integer primary key autoincrement,
            task_id text not null,
            job_id text not null,
            stage text not null,
            event_type text not null,
            payload_json text not null default '{}',
            created_at text not null
        );
        create index if not exists idx_task_events_task_id on pipeline_task_events(task_id, id);
        """
        with self._conn() as conn:
            conn.executescript(ddl)
            conn.commit()

    @staticmethod
    def _event_insert(conn: sqlite3.Connection, *, task_id: str, job_id: str, stage: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        conn.execute(
            "insert into pipeline_task_events (task_id,job_id,stage,event_type,payload_json,created_at) values (?,?,?,?,?,?)",
            (
                task_id,
                job_id,
                stage,
                event_type,
                _safe_json_dumps(payload or {}),
                _now_iso(),
            ),
        )

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload)
        columns = [
            "job_id", "status", "stage", "progress", "error_code", "error_detail",
            "input_path", "output_path", "options_json", "result_json", "requested_cancel",
            "idempotency_key", "last_event", "created_at", "updated_at", "file_size",
            "file_hash", "library_id", "workspace_path", "source_job_id", "file_name",
        ]
        values = {k: row.get(k, "") for k in columns}
        values["progress"] = int(values.get("progress", 0) or 0)
        values["requested_cancel"] = 1 if bool(values.get("requested_cancel")) else 0
        values["file_size"] = int(values.get("file_size", 0) or 0)
        with self._conn() as conn:
            conn.execute(
                f"insert into pipeline_jobs ({','.join(columns)}) values ({','.join(['?'] * len(columns))})",
                [values[k] for k in columns],
            )
            conn.commit()
        out = dict(values)
        out["requested_cancel"] = bool(out.get("requested_cancel"))
        return out

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("select * from pipeline_jobs where job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["requested_cancel"] = bool(out.get("requested_cancel"))
        return out

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not updates:
            row = self.get_job(job_id)
            if row is None:
                raise KeyError(job_id)
            return row
        payload = dict(updates)
        payload["updated_at"] = _now_iso()
        if "requested_cancel" in payload:
            payload["requested_cancel"] = 1 if bool(payload.get("requested_cancel")) else 0
        keys = list(payload.keys())
        sets = ",".join(f"{k}=?" for k in keys)
        guard_sql = "lower(status) not in (?,?,?)"
        guard_args: list[Any] = ["completed", "failed", "cancelled"]
        if "status" in payload:
            guard_sql = f"({guard_sql} or lower(status)=?)"
            guard_args.append(_norm_status(payload.get("status")))
        args = [payload[k] for k in keys] + [job_id] + guard_args
        with self._conn() as conn:
            cur = conn.execute(f"update pipeline_jobs set {sets} where job_id=? and {guard_sql}", args)
            if cur.rowcount <= 0:
                existing = conn.execute("select 1 from pipeline_jobs where job_id = ?", (job_id,)).fetchone()
                if existing is None:
                    raise KeyError(job_id)
            conn.commit()
        row = self.get_job(job_id)
        if row is None:
            raise KeyError(job_id)
        return row

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        return self.update_job(job_id, {"requested_cancel": True})

    def delete_job(self, job_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM pipeline_jobs WHERE job_id = ?", (job_id,))
        conn.commit()

    def enqueue_stage_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        row = {
            "id": str(payload.get("id", "") or f"task_{uuid.uuid4().hex}"),
            "job_id": str(payload.get("job_id", "") or "").strip(),
            "stage": str(payload.get("stage", "") or "").strip(),
            "status": str(payload.get("status", "") or "queued").strip().lower(),
            "priority": int(payload.get("priority", 100) or 100),
            "attempt": int(payload.get("attempt", 0) or 0),
            "max_attempts": int(payload.get("max_attempts", 3) or 3),
            "worker_id": str(payload.get("worker_id", "") or "").strip(),
            "lease_until": str(payload.get("lease_until", "") or "").strip(),
            "heartbeat_at": str(payload.get("heartbeat_at", "") or "").strip(),
            "idempotency_key": str(payload.get("idempotency_key", "") or "").strip(),
            "depends_on_task_id": str(payload.get("depends_on_task_id", "") or "").strip(),
            "input_json": _safe_json_dumps(payload.get("input_json", {}) or {}),
            "output_json": _safe_json_dumps(payload.get("output_json", {}) or {}),
            "error_code": str(payload.get("error_code", "") or "").strip(),
            "error_detail": str(payload.get("error_detail", "") or "").strip(),
            "created_at": str(payload.get("created_at", "") or now),
            "updated_at": str(payload.get("updated_at", "") or now),
        }
        if not row["job_id"] or not row["stage"] or not row["idempotency_key"]:
            raise ValueError("enqueue_stage_task requires job_id, stage, idempotency_key")
        cols = list(row.keys())
        with self._conn() as conn:
            conn.execute(
                f"insert into pipeline_stage_tasks ({','.join(cols)}) values ({','.join(['?'] * len(cols))})",
                [row[c] for c in cols],
            )
            self._event_insert(
                conn,
                task_id=row["id"],
                job_id=row["job_id"],
                stage=row["stage"],
                event_type="queued",
                payload={"priority": row["priority"]},
            )
            conn.commit()
        return dict(row)

    def claim_stage_task(self, stage: str, worker_id: str, lease_seconds: int = 120, extract_limit: int = 3) -> dict[str, Any] | None:
        stage = str(stage or "").strip().lower()
        worker_id = str(worker_id or "").strip()
        if not stage or not worker_id:
            return None
        lease_seconds = max(30, int(lease_seconds or 120))
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if stage == "paper_extract":
                running = int(
                    conn.execute(
                        "select count(*) from pipeline_stage_tasks where stage='paper_extract' and status='running'"
                    ).fetchone()[0]
                )
                if running >= max(1, int(extract_limit or 3)):
                    conn.commit()
                    return None
            row = conn.execute(
                """
                select * from pipeline_stage_tasks
                where stage=? and status='queued'
                order by priority asc, created_at asc
                limit 1
                """,
                (stage,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            task_id = str(row["id"])
            now = datetime.now(timezone.utc)
            lease_until = (now.timestamp() + lease_seconds)
            lease_iso = datetime.fromtimestamp(lease_until, tz=timezone.utc).isoformat()
            cur = conn.execute(
                """
                update pipeline_stage_tasks
                set status='running',
                    worker_id=?,
                    attempt=attempt+1,
                    heartbeat_at=?,
                    lease_until=?,
                    updated_at=?
                where id=? and status='queued'
                """,
                (worker_id, now.isoformat(), lease_iso, now.isoformat(), task_id),
            )
            if cur.rowcount <= 0:
                conn.commit()
                return None
            row2 = conn.execute("select * from pipeline_stage_tasks where id=?", (task_id,)).fetchone()
            self._event_insert(
                conn,
                task_id=task_id,
                job_id=str(row["job_id"]),
                stage=stage,
                event_type="started",
                payload={"worker_id": worker_id, "lease_seconds": lease_seconds},
            )
            conn.commit()
        return dict(row2) if row2 is not None else None

    def heartbeat_stage_task(self, task_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
        task_id = str(task_id or "").strip()
        worker_id = str(worker_id or "").strip()
        if not task_id or not worker_id:
            return False
        now = datetime.now(timezone.utc)
        lease_iso = datetime.fromtimestamp(now.timestamp() + max(30, int(lease_seconds or 120)), tz=timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                update pipeline_stage_tasks
                set heartbeat_at=?, lease_until=?, updated_at=?
                where id=? and worker_id=? and status='running'
                """,
                (now.isoformat(), lease_iso, now.isoformat(), task_id, worker_id),
            )
            if cur.rowcount <= 0:
                conn.commit()
                return False
            row = conn.execute("select job_id,stage from pipeline_stage_tasks where id=?", (task_id,)).fetchone()
            if row is not None:
                self._event_insert(
                    conn,
                    task_id=task_id,
                    job_id=str(row["job_id"]),
                    stage=str(row["stage"]),
                    event_type="heartbeat",
                    payload={"worker_id": worker_id},
                )
            conn.commit()
        return True

    def complete_stage_task(self, task_id: str, worker_id: str, output_json: dict[str, Any] | None = None) -> bool:
        now = _now_iso()
        with self._conn() as conn:
            cur = conn.execute(
                """
                update pipeline_stage_tasks
                set status='completed', output_json=?, error_code='', error_detail='', updated_at=?
                where id=? and worker_id=? and status='running'
                """,
                (_safe_json_dumps(output_json or {}), now, task_id, worker_id),
            )
            if cur.rowcount <= 0:
                conn.commit()
                return False
            row = conn.execute("select job_id,stage from pipeline_stage_tasks where id=?", (task_id,)).fetchone()
            if row is not None:
                self._event_insert(
                    conn,
                    task_id=task_id,
                    job_id=str(row["job_id"]),
                    stage=str(row["stage"]),
                    event_type="completed",
                    payload={},
                )
            conn.commit()
        return True

    def fail_stage_task(
        self,
        task_id: str,
        worker_id: str,
        error_code: str,
        error_detail: str,
        *,
        retryable: bool,
        backoff_seconds: int = 0,
    ) -> bool:
        now = _now_iso()
        with self._conn() as conn:
            row = conn.execute(
                "select * from pipeline_stage_tasks where id=? and worker_id=? and status='running'",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                conn.commit()
                return False
            attempt = int(row["attempt"] or 0)
            max_attempts = int(row["max_attempts"] or 0)
            can_retry = bool(retryable and attempt < max_attempts)
            if can_retry:
                conn.execute(
                    """
                    update pipeline_stage_tasks
                    set status='queued', worker_id='', lease_until='', error_code=?, error_detail=?, updated_at=?
                    where id=?
                    """,
                    (error_code, error_detail, now, task_id),
                )
                self._event_insert(
                    conn,
                    task_id=task_id,
                    job_id=str(row["job_id"]),
                    stage=str(row["stage"]),
                    event_type="retrying",
                    payload={"attempt": attempt, "backoff_seconds": max(0, int(backoff_seconds or 0))},
                )
            else:
                conn.execute(
                    """
                    update pipeline_stage_tasks
                    set status='failed', error_code=?, error_detail=?, updated_at=?
                    where id=?
                    """,
                    (error_code, error_detail, now, task_id),
                )
                conn.execute(
                    """
                    update pipeline_jobs
                    set status='failed', stage=?, error_code=?, error_detail=?, last_event='failed', updated_at=?
                    where job_id=?
                    """,
                    (str(row["stage"]), error_code, error_detail, now, str(row["job_id"])),
                )
                self._event_insert(
                    conn,
                    task_id=task_id,
                    job_id=str(row["job_id"]),
                    stage=str(row["stage"]),
                    event_type="failed",
                    payload={"attempt": attempt},
                )
            conn.commit()
        return True

    def requeue_stale_running_tasks(self, lease_grace_seconds: int = 0) -> int:
        now = datetime.now(timezone.utc).timestamp() - max(0, int(lease_grace_seconds or 0))
        now_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "select id,job_id,stage from pipeline_stage_tasks where status='running' and lease_until <> '' and lease_until < ?",
                (now_iso,),
            ).fetchall()
            if not rows:
                conn.commit()
                return 0
            conn.execute(
                "update pipeline_stage_tasks set status='queued', worker_id='', updated_at=? where status='running' and lease_until <> '' and lease_until < ?",
                (_now_iso(), now_iso),
            )
            for r in rows:
                self._event_insert(
                    conn,
                    task_id=str(r["id"]),
                    job_id=str(r["job_id"]),
                    stage=str(r["stage"]),
                    event_type="retrying",
                    payload={"reason": "lease_expired"},
                )
            conn.commit()
            return len(rows)

    def list_stage_tasks(self, job_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                select *
                from pipeline_stage_tasks
                where job_id=?
                order by
                    case stage
                        when 'mineru_parse' then 1
                        when 'paper_extract' then 2
                        when 'embedding' then 3
                        else 100
                    end asc,
                    created_at asc
                """,
                (job_id,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                for key in ("input_json", "output_json"):
                    raw = item.get(key)
                    if isinstance(raw, str) and raw.strip():
                        try:
                            item[key] = json.loads(raw)
                        except Exception:
                            item[key] = {"raw": raw}
                    elif raw is None:
                        item[key] = {}
                out.append(item)
            return out

    def list_jobs(
        self,
        *,
        library_id: str = "",
        status: str = "",
        query: str = "",
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        args: list[Any] = []
        if str(library_id or "").strip():
            clauses.append("library_id = ?")
            args.append(str(library_id or "").strip())
        if str(status or "").strip():
            clauses.append("lower(status) = ?")
            args.append(str(status or "").strip().lower())
        if str(query or "").strip():
            q = f"%{str(query).strip().lower()}%"
            clauses.append("(lower(job_id) like ? or lower(file_name) like ? or lower(input_path) like ? or lower(error_detail) like ?)")
            args.extend([q, q, q, q])
        where = (" where " + " and ".join(clauses)) if clauses else ""
        order = "created_at asc" if sort == "created_at_asc" else "created_at desc"
        limit = max(1, int(page_size))
        offset = max(0, (max(1, int(page)) - 1) * limit)
        with self._conn() as conn:
            total = int(conn.execute(f"select count(*) from pipeline_jobs{where}", args).fetchone()[0])
            rows = conn.execute(
                f"select * from pipeline_jobs{where} order by {order} limit ? offset ?",
                args + [limit, offset],
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["requested_cancel"] = bool(item.get("requested_cancel"))
            out.append(item)
        return out, total


def _public_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    out = dict(job)
    for key in ("options_json", "result_json"):
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                out[key[:-5]] = json.loads(raw)
            except Exception:
                out[key[:-5]] = raw
    stage = str(out.get("stage", "") or "").strip().lower()
    stage_label_map = {
        "accepted": "排队中",
        "mineru_parse": "解析中",
        "paper_extract": "实体抽取中",
        "embedding": "向量构建中",
        "parse_pdf": "解析中",
        "extract_entities": "实体抽取中",
        "finalize": "入库与索引中",
    }
    status = str(out.get("status", "") or "").strip().lower()
    # UX rule: only completed jobs may show 100%.
    try:
        p = int(out.get("progress", 0) or 0)
    except Exception:
        p = 0
    if status != "completed":
        p = min(99, max(0, p))
    else:
        p = min(100, max(0, p))
    out["progress"] = p
    base_label = stage_label_map.get(stage, stage or "")
    if status == "completed":
        base_label = "完成"
    elif status == "failed":
        failed_label_map = {
            "mineru_parse": "解析失败",
            "paper_extract": "抽取失败",
            "embedding": "向量构建失败",
            "parse_pdf": "解析失败",
            "extract_entities": "抽取失败",
            "finalize": "入库失败",
        }
        base_label = failed_label_map.get(stage, f"{base_label}失败" if base_label else "失败")
    elif status == "cancelled":
        base_label = f"{base_label}已取消" if base_label else "已取消"
    display_name = str(out.get("file_name", "") or "").strip() or str(out.get("job_id", "") or "").strip()
    out["display_name"] = display_name
    out["status_code"] = status
    out["stage_code"] = stage
    out["stage_label"] = base_label
    out["can_cancel"] = status in {"queued", "running"}
    out["can_retry"] = status in {"failed", "cancelled"}
    result_obj = out.get("result")
    if isinstance(result_obj, dict):
        out["final_verdict"] = str(result_obj.get("final_verdict", "") or "")
        out["imported_paper_count"] = int(result_obj.get("imported_paper_count", 0) or 0)
        out["graph_updated"] = bool(result_obj.get("graph_updated", False))
        out["graph_output_path"] = str(result_obj.get("graph_output_path", "") or "")
        out["workspace_path"] = str(result_obj.get("workspace_path", out.get("workspace_path", "")) or "")
        out["library_id"] = str(result_obj.get("library_id", out.get("library_id", "")) or "")
        out["failure_stage"] = str(result_obj.get("failure_stage", "") or "")
        out["failure_code"] = str(result_obj.get("failure_code", out.get("error_code", "")) or "")
    else:
        out["final_verdict"] = "success" if status == "completed" else ("failed" if status == "failed" else "")
        out["imported_paper_count"] = 0
        out["graph_updated"] = False
        out["graph_output_path"] = ""
        out["failure_stage"] = ""
        out["failure_code"] = str(out.get("error_code", "") or "")
    return out


class PipelineService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store: _InMemoryJobStore | _SQLiteJobStore | None = None
        self._runs_root = self._settings.data_dir / "runs"

    def _ensure_store(self) -> _InMemoryJobStore | _SQLiteJobStore:
        if self._store is not None:
            return self._store
        dsn = (self._settings.pipeline_job_store_dsn or "").strip()
        if dsn.startswith("sqlite:///"):
            db_path = Path(dsn[len("sqlite:///"):])
            self._store = _SQLiteJobStore(db_path)
        else:
            self._store = _SQLiteJobStore(self._settings.pipeline_db_path)
        return self._store

    def health(self) -> dict[str, Any]:
        executor = (self._settings.pipeline_executor or "inline").strip().lower()
        return {
            "status": "ok",
            "executor": executor if executor in {"celery", "inline", "stage_queue"} else "inline",
        }

    def list_jobs(
        self,
        *,
        library_id: str = "",
        status: str = "",
        query: str = "",
        sort: str = "created_at_desc",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        store = self._ensure_store()
        rows, total = store.list_jobs(
            library_id=library_id,
            status=status,
            query=query,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        return {
            "jobs": [_public_job_payload(x) for x in rows],
            "total": int(total),
            "page": max(1, int(page)),
            "page_size": max(1, int(page_size)),
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        store = self._ensure_store()
        row = store.get_job(job_id)
        if row is None:
            return None
        return _public_job_payload(row)

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        store = self._ensure_store()
        row = store.get_job(job_id)
        if row is None:
            return None
        raw_result = str(row.get("result_json", "") or "{}")
        try:
            result = json.loads(raw_result)
        except Exception:
            result = {"raw": raw_result}
        if str(row.get("status", "")) != "completed":
            return {
                "error": "result_not_ready",
                "job_id": job_id,
                "status": row.get("status", ""),
                "final_verdict": str(result.get("final_verdict", "failed") or "failed"),
                "failure_stage": str(result.get("failure_stage", row.get("stage", "")) or ""),
                "failure_code": str(result.get("failure_code", row.get("error_code", "")) or ""),
                "result": result,
            }
        return {
            "job_id": job_id,
            "status": "completed",
            "final_verdict": str(result.get("final_verdict", "success") or "success"),
            "imported_paper_count": int(result.get("imported_paper_count", 0) or 0),
            "graph_updated": bool(result.get("graph_updated", False)),
            "workspace_path": str(result.get("workspace_path", "") or ""),
            "library_id": str(result.get("library_id", "") or ""),
            "result": result,
        }

    def get_job_stages(self, job_id: str) -> dict[str, Any]:
        store = self._ensure_store()
        row = store.get_job(job_id)
        if row is None:
            return {"error": "job_not_found", "job_id": job_id}
        if not hasattr(store, "list_stage_tasks"):
            return {"job_id": job_id, "stages": []}
        stage_rows = store.list_stage_tasks(job_id)
        stages: list[dict[str, Any]] = []
        for x in stage_rows:
            stages.append(
                {
                    "task_id": str(x.get("id", "") or ""),
                    "stage": str(x.get("stage", "") or ""),
                    "status": str(x.get("status", "") or ""),
                    "priority": int(x.get("priority", 100) or 100),
                    "attempt": int(x.get("attempt", 0) or 0),
                    "max_attempts": int(x.get("max_attempts", 0) or 0),
                    "worker_id": str(x.get("worker_id", "") or ""),
                    "lease_until": str(x.get("lease_until", "") or ""),
                    "heartbeat_at": str(x.get("heartbeat_at", "") or ""),
                    "error_code": str(x.get("error_code", "") or ""),
                    "error_detail": str(x.get("error_detail", "") or ""),
                    "created_at": str(x.get("created_at", "") or ""),
                    "updated_at": str(x.get("updated_at", "") or ""),
                }
            )
        return {
            "job_id": job_id,
            "job_status": str(row.get("status", "") or ""),
            "job_stage": str(row.get("stage", "") or ""),
            "stages": stages,
        }

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = self._ensure_store()
        return store.create_job(payload)

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        store = self._ensure_store()
        return store.update_job(job_id, updates)

    def enqueue_stage_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = self._ensure_store()
        if not hasattr(store, "enqueue_stage_task"):
            raise RuntimeError("stage_task_not_supported")
        return store.enqueue_stage_task(payload)

    def claim_stage_task(self, stage: str, worker_id: str, lease_seconds: int = 120, extract_limit: int = 3) -> dict[str, Any] | None:
        store = self._ensure_store()
        if not hasattr(store, "claim_stage_task"):
            return None
        return store.claim_stage_task(stage, worker_id, lease_seconds=lease_seconds, extract_limit=extract_limit)

    def heartbeat_stage_task(self, task_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
        store = self._ensure_store()
        if not hasattr(store, "heartbeat_stage_task"):
            return False
        return bool(store.heartbeat_stage_task(task_id, worker_id, lease_seconds=lease_seconds))

    def complete_stage_task(self, task_id: str, worker_id: str, output_json: dict[str, Any] | None = None) -> bool:
        store = self._ensure_store()
        if not hasattr(store, "complete_stage_task"):
            return False
        return bool(store.complete_stage_task(task_id, worker_id, output_json=output_json))

    def fail_stage_task(
        self,
        task_id: str,
        worker_id: str,
        error_code: str,
        error_detail: str,
        *,
        retryable: bool,
        backoff_seconds: int = 0,
    ) -> bool:
        store = self._ensure_store()
        if not hasattr(store, "fail_stage_task"):
            return False
        return bool(
            store.fail_stage_task(
                task_id,
                worker_id,
                error_code,
                error_detail,
                retryable=retryable,
                backoff_seconds=backoff_seconds,
            )
        )

    def requeue_stale_stage_tasks(self, lease_grace_seconds: int = 0) -> int:
        store = self._ensure_store()
        if not hasattr(store, "requeue_stale_running_tasks"):
            return 0
        return int(store.requeue_stale_running_tasks(lease_grace_seconds=lease_grace_seconds))

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        store = self._ensure_store()
        row = store.get_job(job_id)
        if row is None:
            return {"error": "job_not_found", "job_id": job_id}
        cur_status = str(row.get("status", "") or "").strip().lower()
        if cur_status in {"completed", "failed", "cancelled"}:
            return {"error": "job_not_cancellable", "job_id": job_id, "status": str(row.get("status", "") or "")}
        store.request_cancel(job_id)
        try:
            updated = store.update_job(job_id, {
                "status": "cancelled",
                "last_event": "cancelled",
                "error_code": "job_cancelled_by_user",
                "error_detail": "cancel requested by user",
            })
            updated_status = _norm_status(updated.get("status"))
            if updated_status != "cancelled":
                return {"error": "job_cancel_race_conflict", "job_id": job_id, "status": str(updated.get("status", "") or "")}
            return {"job_id": job_id, "status": updated.get("status", ""), "cancel_requested": bool(updated.get("requested_cancel"))}
        except KeyError:
            return {"error": "job_not_found", "job_id": job_id}

    def delete_job(self, job_id: str) -> dict[str, Any] | None:
        store = self._ensure_store()
        row = store.get_job(job_id)
        if row is None:
            return None
        # Clean up job directory
        import shutil
        input_path = str(row.get("input_path", "") or "").strip()
        if input_path:
            job_dir = Path(input_path).resolve().parent.parent
            if job_dir.exists():
                try:
                    shutil.rmtree(job_dir, ignore_errors=True)
                except Exception:
                    pass
        # Remove from store
        if hasattr(store, "delete_job"):
            store.delete_job(job_id)
        return {"job_id": job_id, "deleted": True}

    def retry_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.get_job(job_id)
        if row is None:
            return None
        status = str(row.get("status", "") or "").strip().lower()
        if status not in {"failed", "cancelled"}:
            return {"error": "job_not_retryable", "job_id": job_id, "status": str(row.get("status", "") or "")}
        return None

    @staticmethod
    def _resolve_run_dir_from_row(row: dict[str, Any]) -> Path | None:
        options_raw = str(row.get("options_json", "") or "").strip()
        if options_raw:
            try:
                options_obj = json.loads(options_raw)
                if isinstance(options_obj, dict):
                    root_raw = str(options_obj.get("_job_root", "") or "").strip()
                    if root_raw:
                        return (Path(root_raw).resolve() / "run")
            except Exception:
                pass
        input_path = str(row.get("input_path", "") or "").strip()
        if input_path:
            p = Path(input_path).resolve()
            return p.parent.parent / "run"
        return None

    def get_agent_events(self, job_id: str, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        store = self._ensure_store()
        row = store.get_job(job_id)
        if row is None:
            return {"error": "job_not_found", "job_id": job_id}
        run_dir = self._resolve_run_dir_from_row(row)
        if run_dir is None:
            return {"events": [], "cursor": max(0, int(cursor)), "done": True}
        log_path = run_dir / "events" / "agent_events.jsonl"
        rows: list[dict[str, Any]] = []
        if log_path.exists():
            try:
                with log_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        text = line.strip()
                        if not text:
                            continue
                        try:
                            obj = json.loads(text)
                        except Exception:
                            continue
                        if isinstance(obj, dict):
                            rows.append(obj)
            except Exception:
                rows = []
        cur = max(0, int(cursor))
        lim = max(1, min(1000, int(limit)))
        sliced = rows[cur:cur + lim]
        next_cursor = cur + len(sliced)
        status = _norm_status(row.get("status"))
        done = status in TERMINAL_JOB_STATUSES and next_cursor >= len(rows)
        return {
            "events": sliced,
            "cursor": next_cursor,
            "done": done,
            "total": len(rows),
        }
