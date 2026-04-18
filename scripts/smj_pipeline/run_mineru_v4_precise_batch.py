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
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_mineru_v4", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run MinerU v4 precise batch parsing with daily quota guard and resume.")
    p.add_argument("--manifest", type=Path, required=True, help="Manifest jsonl (recommend: manifest_pdf_v4.jsonl).")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--api-key-env", default="MINERU_API_KEY")
    p.add_argument("--base-url", default="https://mineru.net/api/v4")
    p.add_argument("--model-version", default="vlm")
    p.add_argument("--language", default="en")
    p.add_argument("--enable-table", action="store_true", default=True)
    p.add_argument("--disable-table", action="store_true")
    p.add_argument("--is-ocr", action="store_true", default=False)
    p.add_argument("--enable-formula", action="store_true", default=True)
    p.add_argument("--disable-formula", action="store_true")
    p.add_argument("--submit-interval-seconds", type=float, default=2.0)
    p.add_argument("--poll-interval-seconds", type=float, default=8.0)
    p.add_argument("--max-poll-seconds", type=int, default=3600)
    p.add_argument("--max-inflight", type=int, default=2, help="Provider-safe parallel in-flight parsing tasks.")
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--retry-delays", default="8,20,60")
    p.add_argument("--daily-page-limit", type=int, default=0, help="0 means unlimited.")
    p.add_argument("--daily-file-limit", type=int, default=5000, help="0 means unlimited.")
    p.add_argument("--daily-state-file", type=Path, default=None)
    p.add_argument("--limit", type=int, default=0, help="Only process first N pending records.")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
    return values or [8.0, 20.0, 60.0]


def _jitter_sleep(base_seconds: float) -> None:
    noise = random.uniform(-0.2, 0.2) * max(1.0, base_seconds)
    time.sleep(max(0.0, base_seconds + noise))


def _is_retryable(message: str) -> bool:
    text = str(message or "").lower()
    keywords = (
        "429",
        "limit",
        "frequency",
        "busy",
        "timeout",
        "network",
        "exceeded",
        "限频",
        "超时",
    )
    return any(k in text for k in keywords)


def _bool_choice(default_true: bool, disable_flag: bool) -> bool:
    return False if disable_flag else default_true


def _load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return fallback


def _load_checkpoint(path: Path) -> dict[str, Any]:
    obj = _load_json(path, {"items": {}, "updated_at": _now_iso()})
    if not isinstance(obj.get("items"), dict):
        obj["items"] = {}
    return obj


def _load_daily_state(path: Path) -> dict[str, Any]:
    today = _today_str()
    obj = _load_json(path, {})
    if str(obj.get("date", "")) != today:
        return {"date": today, "submitted_pages": 0, "submitted_files": 0, "done_files": 0, "failed_files": 0, "updated_at": _now_iso()}
    return {
        "date": today,
        "submitted_pages": int(obj.get("submitted_pages", 0)),
        "submitted_files": int(obj.get("submitted_files", 0)),
        "done_files": int(obj.get("done_files", 0)),
        "failed_files": int(obj.get("failed_files", 0)),
        "updated_at": str(obj.get("updated_at", _now_iso())),
    }


def _save_daily_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now_iso()
    write_json_atomic(path, state)


def _task_dir(base: Path, item_id: str) -> Path:
    p = base / safe_id(item_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _append_poll(task_path: Path, row: dict[str, Any]) -> None:
    poll_path = task_path / "poll_log.json"
    payload = _load_json(poll_path, {"rows": []})
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    rows.append(row)
    payload["rows"] = rows
    write_json_atomic(poll_path, payload)


def _submit_one(
    item: dict[str, Any],
    args: argparse.Namespace,
    task_root: Path,
    headers: dict[str, str],
    retry_delays: list[float],
) -> dict[str, Any]:
    item_id = str(item.get("item_id", "")).strip()
    pdf_path = Path(str(item.get("pdf_path", "")).strip())
    page_count = int(item.get("page_count", 0) or 0)
    if not item_id:
        return {"status": "failed", "error": "missing_item_id"}
    if not pdf_path.exists():
        return {"status": "failed", "error": f"missing_pdf:{pdf_path}"}
    if page_count <= 0:
        return {"status": "failed", "error": f"invalid_page_count:{page_count}"}

    task_path = _task_dir(task_root, item_id)
    create_payload = {
        "files": [{"name": str(item.get("file_name", pdf_path.name)), "data_id": item_id}],
        "model_version": str(args.model_version),
        "enable_table": _bool_choice(True, args.disable_table),
        "is_ocr": bool(args.is_ocr),
        "enable_formula": _bool_choice(True, args.disable_formula),
        "language": str(args.language),
    }
    write_json(task_path / "request_file_urls.json", create_payload)

    create_url = f"{str(args.base_url).rstrip('/')}/file-urls/batch"
    attempts = max(1, int(args.max_retries))
    for attempt in range(1, attempts + 1):
        started_at = _now_iso()
        try:
            _log(f"[submit] item={item_id} attempt={attempt}/{attempts} ask upload url")
            res = requests.post(create_url, headers=headers, json=create_payload, timeout=60)
            (task_path / "response_file_urls_status.txt").write_text(str(res.status_code), encoding="utf-8")
            (task_path / "response_file_urls.json").write_text(res.text, encoding="utf-8")
            if res.status_code != 200:
                msg = f"create_http:{res.status_code}"
                if attempt < attempts and _is_retryable(msg):
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    _log(f"[submit] item={item_id} retry create http={res.status_code}, backoff={delay}s")
                    _jitter_sleep(delay)
                    continue
                return {"status": "failed", "error": msg, "attempt": attempt, "started_at": started_at}

            obj = res.json()
            if int(obj.get("code", -1)) != 0:
                msg = f"create_code:{obj.get('code')}:{obj.get('msg')}"
                if attempt < attempts and _is_retryable(msg):
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    _log(f"[submit] item={item_id} retry create code={obj.get('code')}, backoff={delay}s")
                    _jitter_sleep(delay)
                    continue
                return {"status": "failed", "error": msg, "attempt": attempt, "started_at": started_at}

            data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
            batch_id = str(data.get("batch_id", "")).strip()
            file_urls = data.get("file_urls")
            upload_url = str(file_urls[0]).strip() if isinstance(file_urls, list) and file_urls else ""
            if not batch_id or not upload_url:
                return {"status": "failed", "error": "missing_batch_id_or_upload_url", "attempt": attempt, "started_at": started_at}

            with pdf_path.open("rb") as f:
                up = requests.put(upload_url, data=f, timeout=300)
            (task_path / "response_upload_status.txt").write_text(str(up.status_code), encoding="utf-8")
            (task_path / "response_upload.txt").write_text((up.text or "")[:10000], encoding="utf-8")
            if up.status_code not in (200, 201):
                msg = f"upload_http:{up.status_code}"
                if attempt < attempts and _is_retryable(msg):
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    _log(f"[submit] item={item_id} retry upload http={up.status_code}, backoff={delay}s")
                    _jitter_sleep(delay)
                    continue
                return {"status": "failed", "error": msg, "attempt": attempt, "started_at": started_at}

            (task_path / "batch_id.txt").write_text(batch_id, encoding="utf-8")
            return {
                "status": "submitted",
                "batch_id": batch_id,
                "attempt": attempt,
                "started_at": started_at,
                "submitted_at": _now_iso(),
                "next_poll_at": time.time() + float(args.poll_interval_seconds),
            }
        except Exception as exc:
            msg = f"exception:{type(exc).__name__}:{exc}"
            if attempt < attempts and _is_retryable(msg):
                delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                _log(f"[submit] item={item_id} retry exception, backoff={delay}s ({msg})")
                _jitter_sleep(delay)
                continue
            return {"status": "failed", "error": msg, "attempt": attempt, "started_at": started_at}

    return {"status": "failed", "error": "unknown_submit_failure"}


def _poll_one(
    item: dict[str, Any],
    args: argparse.Namespace,
    task_root: Path,
    headers: dict[str, str],
) -> dict[str, Any]:
    item_id = str(item.get("item_id", "")).strip()
    batch_id = str(item.get("batch_id", "")).strip()
    if not batch_id:
        return {"status": "failed", "error": "missing_batch_id"}
    task_path = _task_dir(task_root, item_id)

    poll_url = f"{str(args.base_url).rstrip('/')}/extract-results/batch/{batch_id}"
    res = requests.get(poll_url, headers=headers, timeout=60)
    obj: dict[str, Any]
    try:
        obj = res.json()
    except Exception:
        obj = {"raw": res.text[:5000]}

    _append_poll(
        task_path,
        {
            "at": _now_iso(),
            "http": res.status_code,
            "body": obj,
        },
    )

    if res.status_code != 200:
        return {
            "status": "running",
            "error": f"poll_http:{res.status_code}",
            "next_poll_at": time.time() + float(args.poll_interval_seconds),
        }
    if int(obj.get("code", -1)) != 0:
        return {
            "status": "running",
            "error": f"poll_code:{obj.get('code')}:{obj.get('msg')}",
            "next_poll_at": time.time() + float(args.poll_interval_seconds),
        }

    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    result_list = data.get("extract_result")
    row = result_list[0] if isinstance(result_list, list) and result_list and isinstance(result_list[0], dict) else {}
    state = str(row.get("state", "")).lower().strip()
    err_msg = str(row.get("err_msg", "")).strip()
    full_zip_url = str(row.get("full_zip_url", "")).strip()

    if state == "done":
        write_json(task_path / "response_final.json", obj if isinstance(obj, dict) else {"raw": obj})
        zip_http = 0
        zip_path = ""
        if full_zip_url:
            z = requests.get(full_zip_url, timeout=180)
            zip_http = int(z.status_code)
            if z.status_code == 200:
                target = task_root.parent / "zips" / f"{safe_id(item_id)}.zip"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.content)
                zip_path = str(target)
        return {
            "status": "done",
            "full_zip_url": full_zip_url,
            "zip_http": zip_http,
            "zip_path": zip_path,
            "finished_at": _now_iso(),
        }
    if state == "failed":
        write_json(task_path / "response_final.json", obj if isinstance(obj, dict) else {"raw": obj})
        return {"status": "failed", "error": f"remote_failed:{err_msg}", "finished_at": _now_iso()}

    return {
        "status": "running",
        "poll_state": state or "pending",
        "next_poll_at": time.time() + float(args.poll_interval_seconds),
    }


def _export_failed(run_dir: Path, checkpoint: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    items = checkpoint.get("items", {})
    if isinstance(items, dict):
        for item_id, entry in items.items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status", "")).lower() != "failed":
                continue
            out = dict(entry)
            out["item_id"] = item_id
            rows.append(out)
    write_jsonl(run_dir / "failed.jsonl", rows)


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    random.seed(int(args.seed))

    api_key = str(__import__("os").getenv(args.api_key_env, "")).strip()
    if not api_key:
        raise RuntimeError(f"missing env: {args.api_key_env}")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    retry_delays = _parse_retry_delays(args.retry_delays)

    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    task_root = run_dir / "tasks"
    task_root.mkdir(parents=True, exist_ok=True)

    checkpoint_path = run_dir / "checkpoint_v4.json"
    checkpoint = _load_checkpoint(checkpoint_path)
    items_state = checkpoint.setdefault("items", {})
    if not isinstance(items_state, dict):
        checkpoint["items"] = {}
        items_state = checkpoint["items"]

    daily_state_path = args.daily_state_file if args.daily_state_file else (run_dir / "daily_quota_state_v4.json")
    daily_state = _load_daily_state(daily_state_path)

    rows = [r for r in iter_jsonl(args.manifest)]
    prepared: list[dict[str, Any]] = []
    for row in rows:
        doi = str(row.get("doi", "")).strip()
        pdf_path = str(row.get("pdf_path", "")).strip()
        file_name = str(row.get("file_name", "")).strip()
        page_count = int(row.get("page_count", 0) or 0)
        if not doi or not pdf_path:
            continue
        eligible = bool(row.get("eligible", True))
        if not eligible:
            continue
        item_id = safe_id(doi, 120)
        prepared.append(
            {
                "item_id": item_id,
                "doi": doi,
                "doc_class": str(row.get("doc_class", "")),
                "pdf_path": pdf_path,
                "file_name": file_name or Path(pdf_path).name,
                "page_count": page_count,
                "file_size_bytes": int(row.get("file_size_bytes", 0) or 0),
            }
        )
    if int(args.limit) > 0:
        prepared = prepared[: int(args.limit)]

    prepared_map = {r["item_id"]: r for r in prepared}

    for item in prepared:
        item_id = item["item_id"]
        if item_id not in items_state:
            items_state[item_id] = {**item, "status": "pending", "updated_at": _now_iso()}

    checkpoint["updated_at"] = _now_iso()
    write_json_atomic(checkpoint_path, checkpoint)

    inflight_ids: set[str] = set()
    for item_id, entry in items_state.items():
        if item_id not in prepared_map:
            continue
        st = str(entry.get("status", "")).lower()
        if st in ("submitted", "running") and str(entry.get("batch_id", "")).strip():
            inflight_ids.add(item_id)

    pending_ids = [
        it["item_id"]
        for it in prepared
        if str(items_state.get(it["item_id"], {}).get("status", "")).lower() in ("", "pending", "failed")
    ]

    _log(
        "run config "
        + json.dumps(
            {
                "run_dir": str(run_dir),
                "manifest": str(args.manifest),
                "total_records": len(prepared),
                "pending": len(pending_ids),
                "resume_inflight": len(inflight_ids),
                "max_inflight": int(args.max_inflight),
                "daily_page_limit": int(args.daily_page_limit),
                "daily_file_limit": int(args.daily_file_limit),
            },
            ensure_ascii=False,
        )
    )
    _log("daily state " + json.dumps(daily_state, ensure_ascii=False))

    submitted_now = 0
    done_now = 0
    failed_now = 0
    pause_reason = ""
    last_submit_ts = 0.0
    start_ts = time.time()

    while True:
        # 1) poll inflight
        if inflight_ids:
            now = time.time()
            due_ids = []
            for item_id in list(inflight_ids):
                entry = items_state.get(item_id, {})
                next_poll_at = float(entry.get("next_poll_at", 0.0) or 0.0)
                if now >= next_poll_at:
                    due_ids.append(item_id)

            for item_id in due_ids:
                entry = items_state.get(item_id, {})
                item = prepared_map.get(item_id, {})
                poll_age = int(time.time() - datetime.fromisoformat(str(entry.get("submitted_at", _now_iso()))).timestamp()) if entry.get("submitted_at") else 0
                if poll_age > int(args.max_poll_seconds):
                    entry["status"] = "failed"
                    entry["error"] = "poll_timeout"
                    entry["updated_at"] = _now_iso()
                    items_state[item_id] = entry
                    inflight_ids.discard(item_id)
                    failed_now += 1
                    _log(f"[poll-timeout] item={item_id} doi={item.get('doi','')}")
                    continue

                res = _poll_one({**item, **entry}, args, task_root, headers)
                st = str(res.get("status", "")).lower()
                if st == "done":
                    items_state[item_id] = {**entry, **res, "status": "done", "updated_at": _now_iso()}
                    inflight_ids.discard(item_id)
                    done_now += 1
                    daily_state["done_files"] = int(daily_state.get("done_files", 0)) + 1
                    _save_daily_state(daily_state_path, daily_state)
                    _log(f"[done] item={item_id} doi={item.get('doi','')} zip_http={res.get('zip_http',0)}")
                elif st == "failed":
                    items_state[item_id] = {**entry, **res, "status": "failed", "updated_at": _now_iso()}
                    inflight_ids.discard(item_id)
                    failed_now += 1
                    daily_state["failed_files"] = int(daily_state.get("failed_files", 0)) + 1
                    _save_daily_state(daily_state_path, daily_state)
                    _log(f"[failed] item={item_id} doi={item.get('doi','')} error={res.get('error','')}")
                else:
                    items_state[item_id] = {**entry, **res, "status": "running", "updated_at": _now_iso()}
                    _log(f"[poll] item={item_id} state={res.get('poll_state','running')}")

                checkpoint["updated_at"] = _now_iso()
                write_json_atomic(checkpoint_path, checkpoint)

        # 2) submit new items while under inflight limit
        while pending_ids and len(inflight_ids) < int(args.max_inflight):
            next_id = pending_ids[0]
            base = prepared_map[next_id]
            pages = int(base.get("page_count", 0) or 0)

            if int(args.daily_file_limit) > 0 and int(daily_state.get("submitted_files", 0)) >= int(args.daily_file_limit):
                pause_reason = (
                    f"daily_file_limit_reached:{daily_state.get('submitted_files')}/{int(args.daily_file_limit)}"
                )
                _log(f"[pause] {pause_reason}")
                pending_ids = []
                break
            if int(args.daily_page_limit) > 0 and (int(daily_state.get("submitted_pages", 0)) + pages) > int(args.daily_page_limit):
                pause_reason = (
                    f"daily_page_limit_reached:{daily_state.get('submitted_pages')}+{pages}/{int(args.daily_page_limit)}"
                )
                _log(f"[pause] {pause_reason}")
                pending_ids = []
                break

            delta = time.time() - last_submit_ts
            wait_seconds = float(args.submit_interval_seconds) - delta
            if wait_seconds > 0:
                _jitter_sleep(wait_seconds)

            pending_ids.pop(0)
            entry = items_state.get(next_id, {})
            _log(
                f"[submit] item={next_id} doi={base.get('doi','')} pages={pages} "
                f"daily_pages={daily_state.get('submitted_pages',0)}/{int(args.daily_page_limit)} inflight={len(inflight_ids)}"
            )
            res = _submit_one(base, args, task_root, headers, retry_delays)
            last_submit_ts = time.time()
            st = str(res.get("status", "")).lower()

            if st == "submitted":
                items_state[next_id] = {**base, **entry, **res, "status": "submitted", "updated_at": _now_iso()}
                inflight_ids.add(next_id)
                submitted_now += 1
                daily_state["submitted_files"] = int(daily_state.get("submitted_files", 0)) + 1
                daily_state["submitted_pages"] = int(daily_state.get("submitted_pages", 0)) + pages
                _save_daily_state(daily_state_path, daily_state)
                _log(f"[submitted] item={next_id} batch_id={res.get('batch_id','')}")
            else:
                items_state[next_id] = {**base, **entry, **res, "status": "failed", "updated_at": _now_iso()}
                failed_now += 1
                daily_state["failed_files"] = int(daily_state.get("failed_files", 0)) + 1
                _save_daily_state(daily_state_path, daily_state)
                _log(f"[submit-failed] item={next_id} error={res.get('error','')}")

            checkpoint["updated_at"] = _now_iso()
            write_json_atomic(checkpoint_path, checkpoint)

        if not pending_ids and not inflight_ids:
            break
        if pause_reason and not inflight_ids:
            break

        elapsed = int(time.time() - start_ts)
        _log(
            f"[progress] elapsed={elapsed}s pending={len(pending_ids)} inflight={len(inflight_ids)} "
            f"submitted_now={submitted_now} done_now={done_now} failed_now={failed_now} "
            f"daily(submitted_pages={daily_state.get('submitted_pages',0)},submitted_files={daily_state.get('submitted_files',0)})"
        )
        time.sleep(1.0)

    _export_failed(run_dir, checkpoint)
    summary = {
        "run_dir": str(run_dir),
        "manifest": str(args.manifest),
        "total_records": len(prepared),
        "submitted_now": submitted_now,
        "done_now": done_now,
        "failed_now": failed_now,
        "pending_left": len(
            [1 for item_id in prepared_map if str(items_state.get(item_id, {}).get("status", "")).lower() in ("", "pending", "failed")]
        ),
        "inflight_left": len([1 for item_id in prepared_map if str(items_state.get(item_id, {}).get("status", "")).lower() in ("submitted", "running")]),
        "daily_state_file": str(daily_state_path),
        "daily_state": daily_state,
        "pause_reason": pause_reason,
        "checkpoint": str(checkpoint_path),
    }
    write_json(run_dir / "run_v4_summary.json", summary)
    _log("run summary " + json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
