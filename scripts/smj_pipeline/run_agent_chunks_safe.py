from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests

from mineru_agent_common import iter_jsonl, safe_id, write_json, write_json_atomic, write_jsonl


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_mineru_agent", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run MinerU agent chunk parsing with conservative throttling.")
    p.add_argument("--manifest-chunks", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--base-url", default="https://mineru.net/api/v1/agent")
    p.add_argument("--language", default="en")
    p.add_argument("--enable-table", action="store_true", default=True)
    p.add_argument("--disable-table", action="store_true")
    p.add_argument("--is-ocr", action="store_true", default=False)
    p.add_argument("--enable-formula", action="store_true", default=True)
    p.add_argument("--disable-formula", action="store_true")
    p.add_argument("--create-interval-seconds", type=float, default=3.0)
    p.add_argument("--poll-interval-seconds", type=float, default=6.0)
    p.add_argument("--max-poll-seconds", type=int, default=1200)
    p.add_argument("--retry-delays", default="5,15,45")
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--limit", type=int, default=0, help="Only process first N pending chunks for smoke tests.")
    p.add_argument(
        "--daily-max-create",
        type=int,
        default=0,
        help="Daily max create-task requests (includes retries). 0 means unlimited.",
    )
    p.add_argument(
        "--daily-max-done",
        type=int,
        default=0,
        help="Daily max successful chunks. 0 means unlimited.",
    )
    p.add_argument(
        "--daily-state-file",
        type=Path,
        default=None,
        help="State file for daily counters. Default: <run-dir>/daily_quota_state.json",
    )
    p.add_argument("--verbose-poll", action="store_true", default=False, help="Print each poll step.")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def _bool_choice(default_true: bool, disable_flag: bool) -> bool:
    if disable_flag:
        return False
    return default_true


def _parse_retry_delays(text: str) -> list[float]:
    values: list[float] = []
    for part in str(text).split(","):
        t = part.strip()
        if not t:
            continue
        try:
            values.append(float(t))
        except ValueError:
            continue
    return values or [5.0, 15.0, 45.0]


def _jitter_sleep(base_seconds: float) -> None:
    noise = random.uniform(-0.25, 0.25) * max(1.0, base_seconds)
    time.sleep(max(0.0, base_seconds + noise))


def _is_retryable_message(message: str) -> bool:
    text = str(message or "").lower()
    keywords = (
        "limit",
        "frequency",
        "busy",
        "timeout",
        "network",
        "429",
        "闄愰",
        "棰戠巼",
        "瓒呮椂",
    )
    return any(k in text for k in keywords)


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"chunks": {}, "updated_at": _now_iso()}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("chunks"), dict):
            return payload
    except Exception:
        pass
    return {"chunks": {}, "updated_at": _now_iso()}


def _load_daily_state(path: Path) -> dict[str, Any]:
    today = _today_str()
    if not path.exists():
        return {"date": today, "create_count": 0, "done_count": 0, "failed_count": 0, "updated_at": _now_iso()}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("invalid_daily_state")
        if str(obj.get("date", "")) != today:
            return {"date": today, "create_count": 0, "done_count": 0, "failed_count": 0, "updated_at": _now_iso()}
        return {
            "date": str(obj.get("date", today)),
            "create_count": int(obj.get("create_count", 0)),
            "done_count": int(obj.get("done_count", 0)),
            "failed_count": int(obj.get("failed_count", 0)),
            "updated_at": str(obj.get("updated_at", _now_iso())),
        }
    except Exception:
        return {"date": today, "create_count": 0, "done_count": 0, "failed_count": 0, "updated_at": _now_iso()}


def _save_daily_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now_iso()
    write_json_atomic(path, state)


def _task_dir(base: Path, chunk_id: str) -> Path:
    p = base / safe_id(chunk_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_failed(run_dir: Path, checkpoint: dict[str, Any]) -> None:
    failed_rows: list[dict[str, Any]] = []
    chunks = checkpoint.get("chunks", {})
    if isinstance(chunks, dict):
        for chunk_id, entry in chunks.items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status", "")).lower() != "failed":
                continue
            row = dict(entry)
            row["chunk_id"] = chunk_id
            failed_rows.append(row)
    write_jsonl(run_dir / "failed.jsonl", failed_rows)


def _run_one_chunk(
    chunk: dict[str, Any],
    args: argparse.Namespace,
    task_root: Path,
    md_root: Path,
) -> dict[str, Any]:
    chunk_id = str(chunk.get("chunk_id", "")).strip()
    if not chunk_id:
        return {"status": "failed", "error": "missing_chunk_id"}
    task_path = _task_dir(task_root, chunk_id)
    source_pdf = Path(str(chunk.get("pdf_path", "")).strip())
    if not source_pdf.exists():
        result = {"status": "failed", "error": f"missing_pdf:{source_pdf}"}
        write_json(task_path / "result.json", result)
        return result

    payload = {
        "file_name": str(chunk.get("file_name", source_pdf.name)),
        "language": str(args.language),
        "page_range": str(chunk.get("page_range", "")),
        "enable_table": _bool_choice(True, args.disable_table),
        "is_ocr": bool(args.is_ocr),
        "enable_formula": _bool_choice(True, args.disable_formula),
    }
    write_json(task_path / "request_create.json", payload)
    _log(f"[chunk={chunk_id}] create task: page_range={payload['page_range']}")

    create_url = f"{str(args.base_url).rstrip('/')}/parse/file"
    create_response = requests.post(create_url, json=payload, timeout=60)
    create_response_text = create_response.text
    (task_path / "response_create_status.txt").write_text(str(create_response.status_code), encoding="utf-8")
    (task_path / "response_create.json").write_text(create_response_text, encoding="utf-8")
    _log(f"[chunk={chunk_id}] create http={create_response.status_code}")
    create_response.raise_for_status()
    create_obj = create_response.json()
    if int(create_obj.get("code", -1)) != 0:
        return {"status": "failed", "error": f"create_code:{create_obj.get('code')}:{create_obj.get('msg')}"}

    data = create_obj.get("data") if isinstance(create_obj.get("data"), dict) else {}
    task_id = str((data or {}).get("task_id", "")).strip()
    file_url = str((data or {}).get("file_url", "")).strip()
    if not task_id or not file_url:
        return {"status": "failed", "error": "missing_task_id_or_file_url"}
    (task_path / "task_id.txt").write_text(task_id, encoding="utf-8")

    with source_pdf.open("rb") as f:
        upload_response = requests.put(file_url, data=f, timeout=180)
    (task_path / "response_upload_status.txt").write_text(str(upload_response.status_code), encoding="utf-8")
    (task_path / "response_upload.txt").write_text((upload_response.text or "")[:10000], encoding="utf-8")
    _log(f"[chunk={chunk_id}] upload http={upload_response.status_code}")
    if upload_response.status_code not in (200, 201):
        return {"status": "failed", "error": f"upload_http:{upload_response.status_code}", "task_id": task_id}

    poll_url = f"{str(args.base_url).rstrip('/')}/parse/{task_id}"
    poll_rows: list[dict[str, Any]] = []
    start = time.time()
    last_state = ""
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= int(args.max_poll_seconds):
            write_json(task_path / "poll_log.json", {"rows": poll_rows})
            return {"status": "failed", "error": "poll_timeout", "task_id": task_id}

        poll_response = requests.get(poll_url, timeout=60)
        poll_obj: dict[str, Any]
        try:
            poll_obj = poll_response.json()
        except Exception:
            poll_obj = {"raw": poll_response.text[:5000]}

        state = ""
        if isinstance(poll_obj, dict):
            data_obj = poll_obj.get("data")
            if isinstance(data_obj, dict):
                state = str(data_obj.get("state", "")).strip().lower()
        poll_rows.append({"elapsed": elapsed, "http": poll_response.status_code, "state": state, "body": poll_obj})

        if args.verbose_poll or state != last_state:
            _log(f"[chunk={chunk_id}] poll elapsed={elapsed}s http={poll_response.status_code} state={state or '-'}")
        last_state = state

        if state == "done":
            markdown_url = ""
            data_obj = poll_obj.get("data")
            if isinstance(data_obj, dict):
                markdown_url = str(data_obj.get("markdown_url", "")).strip()
            if markdown_url:
                md_response = requests.get(markdown_url, timeout=120)
                md_response.raise_for_status()
                md_path = md_root / f"{safe_id(chunk_id)}.md"
                md_path.write_text(md_response.text, encoding="utf-8")
                write_json(task_path / "poll_log.json", {"rows": poll_rows})
                write_json(task_path / "response_final.json", poll_obj if isinstance(poll_obj, dict) else {"raw": poll_obj})
                return {
                    "status": "done",
                    "task_id": task_id,
                    "markdown_url": markdown_url,
                    "md_chunk_path": str(md_path),
                    "finished_at": _now_iso(),
                }
            write_json(task_path / "poll_log.json", {"rows": poll_rows})
            return {"status": "failed", "error": "done_without_markdown_url", "task_id": task_id}

        if state == "failed":
            err_msg = ""
            err_code: Any = ""
            data_obj = poll_obj.get("data")
            if isinstance(data_obj, dict):
                err_msg = str(data_obj.get("err_msg", "")).strip()
                err_code = data_obj.get("err_code", "")
            write_json(task_path / "poll_log.json", {"rows": poll_rows})
            return {
                "status": "failed",
                "task_id": task_id,
                "error": f"remote_failed:{err_code}:{err_msg}",
                "err_code": err_code,
                "err_msg": err_msg,
            }

        _jitter_sleep(float(args.poll_interval_seconds))


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    random.seed(int(args.seed))
    retry_delays = _parse_retry_delays(args.retry_delays)

    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    task_root = run_dir / "tasks"
    md_root = run_dir / "md_chunks"
    task_root.mkdir(parents=True, exist_ok=True)
    md_root.mkdir(parents=True, exist_ok=True)

    checkpoint_path = run_dir / "checkpoint.json"
    checkpoint = _load_checkpoint(checkpoint_path)
    chunks_state = checkpoint.setdefault("chunks", {})
    if not isinstance(chunks_state, dict):
        checkpoint["chunks"] = {}
        chunks_state = checkpoint["chunks"]

    daily_state_path = args.daily_state_file if args.daily_state_file else (run_dir / "daily_quota_state.json")
    daily_state = _load_daily_state(daily_state_path)

    chunks = list(iter_jsonl(args.manifest_chunks))
    pending = [
        c
        for c in chunks
        if str(chunks_state.get(str(c.get("chunk_id", "")), {}).get("status", "")).lower() != "done"
    ]
    if int(args.limit) > 0:
        pending = pending[: int(args.limit)]

    _log(
        "run config "
        + json.dumps(
            {
                "run_dir": str(run_dir),
                "manifest_chunks": str(args.manifest_chunks),
                "total_chunks": len(chunks),
                "pending_chunks": len(pending),
                "daily_max_create": int(args.daily_max_create),
                "daily_max_done": int(args.daily_max_done),
                "daily_state_file": str(daily_state_path),
            },
            ensure_ascii=False,
        )
    )
    _log(
        "daily quota state "
        + json.dumps(
            {
                "date": daily_state.get("date"),
                "create_count": int(daily_state.get("create_count", 0)),
                "done_count": int(daily_state.get("done_count", 0)),
                "failed_count": int(daily_state.get("failed_count", 0)),
            },
            ensure_ascii=False,
        )
    )

    done_count = 0
    failed_count = 0
    skipped_done = len(chunks) - len(pending)
    last_create_ts = 0.0
    stop_reason = ""
    total_pending = len(pending)

    for idx, chunk in enumerate(pending, start=1):
        chunk_id = str(chunk.get("chunk_id", "")).strip()
        if not chunk_id:
            continue

        if int(args.daily_max_create) > 0 and int(daily_state.get("create_count", 0)) >= int(args.daily_max_create):
            stop_reason = f"daily_create_limit_reached:{daily_state.get('create_count')}/{int(args.daily_max_create)}"
            _log(f"stop by quota: {stop_reason}")
            break
        if int(args.daily_max_done) > 0 and int(daily_state.get("done_count", 0)) >= int(args.daily_max_done):
            stop_reason = f"daily_done_limit_reached:{daily_state.get('done_count')}/{int(args.daily_max_done)}"
            _log(f"stop by quota: {stop_reason}")
            break

        delta = time.time() - last_create_ts
        wait_seconds = float(args.create_interval_seconds) - delta
        if wait_seconds > 0:
            _log(f"[{idx}/{total_pending}] throttle wait={wait_seconds:.2f}s")
            _jitter_sleep(wait_seconds)

        _log(
            f"[{idx}/{total_pending}] start chunk={chunk_id} doi={chunk.get('doi','')} page_range={chunk.get('page_range','')}"
        )

        final_result: dict[str, Any] | None = None
        attempts = max(1, int(args.max_retries))
        for attempt in range(1, attempts + 1):
            started_at = _now_iso()
            daily_state["create_count"] = int(daily_state.get("create_count", 0)) + 1
            _save_daily_state(daily_state_path, daily_state)
            _log(
                f"[{idx}/{total_pending}] attempt={attempt}/{attempts} daily_create={daily_state.get('create_count')} "
                f"daily_done={daily_state.get('done_count',0)}"
            )
            try:
                result = _run_one_chunk(chunk, args, task_root, md_root)
                status = str(result.get("status", "")).lower()
                if status == "done":
                    result["attempt"] = attempt
                    result["started_at"] = started_at
                    final_result = result
                    daily_state["done_count"] = int(daily_state.get("done_count", 0)) + 1
                    _save_daily_state(daily_state_path, daily_state)
                    break

                error_text = str(result.get("error", ""))
                retryable = _is_retryable_message(error_text)
                if retryable and attempt < attempts:
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    _log(f"[{idx}/{total_pending}] retryable error={error_text}; backoff={delay}s")
                    _jitter_sleep(delay)
                    continue
                result["attempt"] = attempt
                result["started_at"] = started_at
                final_result = result
                daily_state["failed_count"] = int(daily_state.get("failed_count", 0)) + 1
                _save_daily_state(daily_state_path, daily_state)
                break
            except Exception as exc:
                err = f"exception:{type(exc).__name__}:{exc}"
                if attempt < attempts:
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    _log(f"[{idx}/{total_pending}] exception={err}; backoff={delay}s")
                    _jitter_sleep(delay)
                    continue
                final_result = {"status": "failed", "error": err, "attempt": attempt, "started_at": started_at}
                daily_state["failed_count"] = int(daily_state.get("failed_count", 0)) + 1
                _save_daily_state(daily_state_path, daily_state)
                break
            finally:
                last_create_ts = time.time()

        if final_result is None:
            final_result = {"status": "failed", "error": "unknown_failure"}

        chunks_state[chunk_id] = {**chunk, **final_result, "updated_at": _now_iso()}
        checkpoint["updated_at"] = _now_iso()
        write_json_atomic(checkpoint_path, checkpoint)

        if str(final_result.get("status", "")).lower() == "done":
            done_count += 1
            _log(f"[{idx}/{total_pending}] done chunk={chunk_id}")
        else:
            failed_count += 1
            _log(f"[{idx}/{total_pending}] failed chunk={chunk_id} error={final_result.get('error','')}")

        _log(
            f"[{idx}/{total_pending}] progress done_now={done_count} failed_now={failed_count} "
            f"daily(create={daily_state.get('create_count',0)},done={daily_state.get('done_count',0)},failed={daily_state.get('failed_count',0)})"
        )

    _save_failed(run_dir, checkpoint)

    summary = {
        "run_dir": str(run_dir),
        "manifest_chunks": str(args.manifest_chunks),
        "total_chunks": len(chunks),
        "processed_chunks": len(pending),
        "skipped_done": skipped_done,
        "done_now": done_count,
        "failed_now": failed_count,
        "checkpoint": str(checkpoint_path),
        "daily_state_file": str(daily_state_path),
        "daily_state": {
            "date": daily_state.get("date"),
            "create_count": int(daily_state.get("create_count", 0)),
            "done_count": int(daily_state.get("done_count", 0)),
            "failed_count": int(daily_state.get("failed_count", 0)),
        },
        "stop_reason": stop_reason,
    }
    write_json(run_dir / "run_agent_chunks_summary.json", summary)
    _log("run summary " + json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
