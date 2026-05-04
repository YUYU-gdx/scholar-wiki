from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
import uuid

from kn_graph.config import Settings

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _load_env_utils():
    module_path = _SCRIPTS_DIR / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_pipeline_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if spec.name not in sys.modules:
        sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


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
        """
        with self._conn() as conn:
            conn.executescript(ddl)
            conn.commit()

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
        "accepted": "待处理",
        "parse_pdf": "解析中",
        "extract_entities": "抽取中",
        "finalize": "整理中",
    }
    status = str(out.get("status", "") or "").strip().lower()
    display_name = str(out.get("file_name", "") or "").strip() or str(out.get("job_id", "") or "").strip()
    out["display_name"] = display_name
    out["status_code"] = status
    out["stage_code"] = stage
    out["stage_label"] = stage_label_map.get(stage, stage or "")
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
        elif dsn and dsn.startswith("postgres"):
            raise RuntimeError("postgres_job_store_not_supported_in_kn_graph_pipeline_service")
        else:
            self._store = _SQLiteJobStore(self._settings.pipeline_db_path)
        return self._store

    def health(self) -> dict[str, Any]:
        executor = (self._settings.pipeline_executor or "inline").strip().lower()
        return {
            "status": "ok",
            "executor": executor if executor in {"celery", "inline"} else "inline",
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

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        store = self._ensure_store()
        return store.create_job(payload)

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        store = self._ensure_store()
        return store.update_job(job_id, updates)

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

    def retry_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.get_job(job_id)
        if row is None:
            return None
        status = str(row.get("status", "") or "").strip().lower()
        if status not in {"failed", "cancelled"}:
            return {"error": "job_not_retryable", "job_id": job_id, "status": str(row.get("status", "") or "")}
        return None
