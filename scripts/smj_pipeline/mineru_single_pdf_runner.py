from __future__ import annotations

import argparse
from datetime import datetime
import html
import importlib.util
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
import zipfile

import fitz  # type: ignore

from mineru_agent_common import safe_id


class MinerUSinglePdfError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code).strip() or "mineru_error"
        self.detail = str(detail)
        super().__init__(f"{self.code}:{self.detail}" if self.detail else self.code)


def _parse_dotenv_value(raw: str) -> str:
    text = str(raw).strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _read_env_key_from_dotenv(dotenv_path: Path, key: str) -> str:
    if not dotenv_path.exists():
        return ""
    try:
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            row = line.strip()
            if not row or row.startswith("#") or "=" not in row:
                continue
            name, value = row.split("=", 1)
            if name.strip() == key:
                return _parse_dotenv_value(value)
    except Exception:
        return ""
    return ""


def _resolve_api_key(env_name: str) -> str:
    key = str(os.getenv(env_name, "")).strip()
    if key:
        return key
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for dotenv_path in candidates:
        val = _read_env_key_from_dotenv(dotenv_path, env_name).strip()
        if val:
            os.environ[env_name] = val
            return val
    return ""


def _load_batch_module():
    module_path = Path(__file__).resolve().parent / "run_mineru_v4_precise_batch.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_run_mineru_v4_precise_batch_for_single", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _page_count(pdf_path: Path) -> int:
    try:
        with fitz.open(str(pdf_path)) as doc:
            return int(doc.page_count)
    except Exception:
        return -1


def _build_args(options: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        base_url=str(options.get("base_url", "https://mineru.net/api/v4")),
        model_version=str(options.get("model_version", "vlm")),
        disable_table=bool(options.get("disable_table", False)),
        is_ocr=bool(options.get("is_ocr", False)),
        disable_formula=bool(options.get("disable_formula", False)),
        language=str(options.get("language", "en")),
        max_retries=int(options.get("max_retries", 3)),
        poll_interval_seconds=float(options.get("poll_interval_seconds", 8.0)),
        max_poll_seconds=int(options.get("max_poll_seconds", 3600)),
    )


def _extract_full_markdown(zip_path: Path, parse_dir: Path) -> tuple[Path, Path]:
    if not zip_path.exists():
        raise MinerUSinglePdfError("mineru_output_missing", f"zip_not_found:{zip_path}")
    unpack_dir = parse_dir / "mineru_zip_unpacked"
    if unpack_dir.exists():
        for p in sorted(unpack_dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                p.rmdir()
    unpack_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(unpack_dir)
    md_candidates = sorted(unpack_dir.rglob("full.md"))
    if not md_candidates:
        raise MinerUSinglePdfError("mineru_output_missing", "full_md_not_found_in_zip")
    source_md = md_candidates[0]
    markdown_path = parse_dir / "parsed.md"
    html_path = parse_dir / "parsed.html"
    markdown = source_md.read_text(encoding="utf-8", errors="ignore")
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(f"<html><body><pre>{html.escape(markdown)}</pre></body></html>", encoding="utf-8")
    return markdown_path, html_path


def parse_single_pdf(
    pdf_path: Path,
    run_dir: Path,
    options: dict[str, Any] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    opts = dict(options or {})
    if not pdf_path.exists():
        raise MinerUSinglePdfError("mineru_input_missing", str(pdf_path))
    batch_mod = _load_batch_module()

    parse_dir = run_dir / "parse"
    parse_dir.mkdir(parents=True, exist_ok=True)
    task_root = parse_dir / "tasks"
    task_root.mkdir(parents=True, exist_ok=True)

    page_count = _page_count(pdf_path)
    if page_count <= 0:
        raise MinerUSinglePdfError("pdf_unreadable", str(pdf_path))

    api_key_env = str(opts.get("api_key_env", "MINERU_API_KEY")).strip() or "MINERU_API_KEY"
    api_key = _resolve_api_key(api_key_env)
    if not api_key:
        raise MinerUSinglePdfError("mineru_api_key_missing", api_key_env)

    args = _build_args(opts)
    retry_delays = batch_mod._parse_retry_delays(str(opts.get("retry_delays", "8,20,60")))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    source_id = str(opts.get("source_id", f"upload::{pdf_path.name}"))
    item_id = safe_id(source_id, 120)
    item = {
        "item_id": item_id,
        "doi": source_id,
        "source_id": source_id,
        "doc_class": "upload",
        "pdf_path": str(pdf_path),
        "file_name": pdf_path.name,
        "page_count": page_count,
        "file_size_bytes": int(pdf_path.stat().st_size),
    }
    if progress_cb is not None:
        progress_cb(8, "submit_start")
    submit_res = batch_mod._submit_one(item, args, task_root, headers, retry_delays)
    if str(submit_res.get("status", "")).lower() != "submitted":
        raise MinerUSinglePdfError("mineru_submit_failed", str(submit_res.get("error", "")))
    if progress_cb is not None:
        progress_cb(18, "submitted")

    entry = {**item, **submit_res, "status": "submitted", "updated_at": datetime.now().isoformat()}
    started_at_ts = time.time()
    while True:
        if cancel_cb is not None and cancel_cb():
            raise MinerUSinglePdfError("job_cancelled", "requested")
        poll_age = int(time.time() - started_at_ts)
        if poll_age > int(args.max_poll_seconds):
            raise MinerUSinglePdfError("mineru_poll_timeout", f"{poll_age}s")
        next_poll_at = float(entry.get("next_poll_at", 0.0) or 0.0)
        now = time.time()
        if now < next_poll_at:
            time.sleep(min(1.0, next_poll_at - now))
            continue
        poll_res = batch_mod._poll_one(entry, args, task_root, headers)
        st = str(poll_res.get("status", "")).lower()
        entry.update({**poll_res, "updated_at": datetime.now().isoformat()})
        if st == "done":
            break
        if st == "failed":
            raise MinerUSinglePdfError("mineru_remote_failed", str(poll_res.get("error", "")))
        if progress_cb is not None:
            progress_cb(min(80, 20 + int((poll_age / max(1, int(args.max_poll_seconds))) * 55)), "polling")
        time.sleep(0.6)

    zip_path = Path(str(entry.get("zip_path", "") or ""))
    markdown_path, html_path = _extract_full_markdown(zip_path, parse_dir)
    result = {
        "markdown_path": str(markdown_path),
        "html_path": str(html_path),
        "zip_path": str(zip_path),
        "page_count": page_count,
        "batch_id": str(entry.get("batch_id", "")),
    }
    (parse_dir / "parse_meta.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_cb is not None:
        progress_cb(45, "parse_done")
    return result
