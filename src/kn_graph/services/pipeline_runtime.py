from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Protocol

from kn_graph.providers.registry import ProviderRegistry
from kn_graph.services.extraction_pipeline import run as run_extraction_mvp, NullLLMClient
from kn_graph.services.graph_builder import _build_artifact_from_sqlite, run_build_from_artifact
from kn_graph.services.import_sqlite import main_inline as _import_sqlite_main_inline
from kn_graph.services.mineru_runner import parse_single_pdf
from kn_graph.services.sqlite_repo import SqliteRepo

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
AGENT_EVENT_LOG_FILENAME = "agent_events.jsonl"


class JobStore(Protocol):
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_status(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _agent_event_log_path(run_dir: Path) -> Path:
    path = run_dir / "events" / AGENT_EVENT_LOG_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _truncate_event_value(value: Any, max_len: int = 4000) -> Any:
    if isinstance(value, str):
        if len(value) <= max_len:
            return value
        return value[:max_len] + "...(truncated)"
    if isinstance(value, dict):
        return {str(k): _truncate_event_value(v, max_len=max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_event_value(v, max_len=max_len) for v in value]
    return value


def _append_agent_event(
    *,
    log_path: Path,
    seq: int,
    job_id: str,
    backend: str,
    event: dict[str, Any],
) -> None:
    payload = {
        "seq": int(seq),
        "ts": _now_iso(),
        "job_id": str(job_id or ""),
        "backend": str(backend or ""),
        "method": str(event.get("method", "") or ""),
        "params": _truncate_event_value(event.get("params", {})),
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.write("\n")
    return payload


def _coerce_authors_json(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("name", "") or "").strip()
                if not name:
                    continue
                affiliation = str(item.get("affiliation", "") or "").strip()
                entry: dict[str, str] = {"name": name}
                if affiliation:
                    entry["affiliation"] = affiliation
                out.append(entry)
            elif isinstance(item, str):
                name = item.strip()
                if name:
                    out.append({"name": name})
    elif isinstance(value, str):
        name = value.strip()
        if name:
            out.append({"name": name})
    return out


def _coerce_publication_year(value: Any, publication_date: str = "") -> int | None:
    text = str(value or "").strip()
    if text:
        try:
            return int(float(text))
        except ValueError:
            pass
    date_text = str(publication_date or "").strip()
    if len(date_text) >= 4 and date_text[:4].isdigit():
        return int(date_text[:4])
    return None


def _extract_agent_paper_metadata(agent_bundle: dict[str, Any]) -> dict[str, Any]:
    metadata = agent_bundle.get("paper_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    publication_date = str(
        metadata.get("publication_date", "")
        or metadata.get("date", "")
        or agent_bundle.get("publication_date", "")
        or ""
    ).strip()
    return {
        "title": str(metadata.get("title", "") or agent_bundle.get("title", "") or "").strip(),
        "authors_json": _coerce_authors_json(metadata.get("authors_json", metadata.get("authors", []))),
        "abstract": str(metadata.get("abstract", "") or agent_bundle.get("abstract", "") or "").strip(),
        "journal": str(
            metadata.get("journal", "")
            or metadata.get("publication_title", "")
            or agent_bundle.get("journal", "")
            or ""
        ).strip(),
        "publication_date": publication_date,
        "online_date": str(metadata.get("online_date", "") or agent_bundle.get("online_date", "") or "").strip(),
        "publication_year": _coerce_publication_year(
            metadata.get("publication_year", agent_bundle.get("publication_year")),
            publication_date=publication_date,
        ),
        "doi": str(metadata.get("doi", "") or agent_bundle.get("doi", "") or "").strip(),
        "article_url": str(
            metadata.get("article_url", "")
            or metadata.get("url", "")
            or agent_bundle.get("article_url", "")
            or ""
        ).strip(),
    }


def _citation_metadata_from_markdown(md_path: Path) -> dict[str, Any]:
    if not md_path.exists():
        return {}
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    cite_line = ""
    for line in text.splitlines():
        if "How to cite this article:" in line:
            cite_line = line.strip()
            break
    if not cite_line:
        return {}

    out: dict[str, Any] = {}
    doi_match = re.search(r"(10\.\d{4,9}/[^\s]+)", cite_line)
    if doi_match:
        out["doi"] = doi_match.group(1).rstrip(").,;")

    year_match = re.search(r"\((19|20)\d{2}\)", cite_line)
    if year_match:
        year_text = year_match.group(0)[1:-1]
        out["publication_year"] = int(year_text)
        out["publication_date"] = year_text

    journal_match = re.search(r"\.\s([^.,\n]*Journal[^,\n]*),\s*\d", cite_line)
    if journal_match:
        out["journal"] = journal_match.group(1).strip()

    # Authors are before "(YYYY)" in the cite line.
    if year_match:
        authors_text = cite_line.split(year_match.group(0), 1)[0]
        authors_text = authors_text.replace("How to cite this article:", "").strip().strip(".")
        # Parse author segments like "Surname, X." while preserving initials.
        matches = re.findall(r"[^,]+,\s*(?:[A-Z](?:\.\s*)?)+(?:[A-Z](?:\.\s*)?)*", authors_text)
        if not matches:
            matches = [s.strip() for s in re.split(r"\s*&\s*", authors_text) if s.strip()]
        authors_json = [{"name": m.strip().lstrip("& ").strip()} for m in matches if m.strip()]
        if authors_json:
            out["authors_json"] = authors_json
    return out


def _ensure_reader_note_written(md_path: Path, job_id: str, bundle: dict[str, Any]) -> None:
    if not md_path.exists():
        return
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    note_id = f"pipeline-{job_id}"
    if f"Note ID: {note_id}" in text:
        return

    direct_effects = bundle.get("direct_effects", [])
    lines: list[str] = []
    if isinstance(direct_effects, list) and direct_effects:
        for row in direct_effects[:6]:
            if not isinstance(row, dict):
                continue
            src = str(row.get("source", "") or "").strip()
            tgt = str(row.get("target", "") or "").strip()
            eff = str(row.get("effect_form", "") or "").strip()
            ver = str(row.get("verification", "") or "").strip()
            if src and tgt:
                lines.append(f"- {src} -> {tgt} ({eff}, {ver})")
    if not lines:
        lines.append("- No validated direct effects extracted.")

    abs_path = str(md_path.resolve()).replace("\\", "/")
    note_text = (
        "\n\n## Reader Notes\n\n"
        "> [!NOTE] Reader Note\n"
        f"> Note ID: {note_id}\n"
        "> Quote:\n"
        "> Automated extraction summary from pipeline run.\n"
        ">\n"
        "> Note:\n"
        f"> Source paper: [full.md]({abs_path})\n"
        f"> Extractability: {str(bundle.get('extractability_status', '') or '').strip()}\n"
        + "".join(f"> {line}\n" for line in lines)
        + ">\n"
        "> Time:\n"
        f"> {datetime.now(timezone.utc).isoformat()}\n"
    )
    md_path.write_text(text + note_text, encoding="utf-8")


def _stage_update(store: JobStore, job_id: str, stage: str, progress: int, event: str, **extra: Any) -> None:
    existing = store.get_job(job_id) or {}
    if _norm_status(existing.get("status")) in TERMINAL_JOB_STATUSES and event != "cancelled":
        return
    payload = {"stage": stage, "progress": int(progress), "last_event": event}
    payload.update(extra)
    store.update_job(job_id, payload)


def _cleanup_redundant_job_files(
    *,
    input_pdf: Path,
    run_dir: Path,
    keep_intermediates: bool,
) -> dict[str, Any]:
    """Remove duplicated parse/input artifacts after successful materialization.

    Keep extraction/event/result artifacts in run_dir, but remove parse outputs and
    the uploaded input PDF copy because canonical assets are under corpus/papers.
    """
    if keep_intermediates:
        return {"cleanup_enabled": False, "removed": []}

    removed: list[str] = []

    parse_dir = run_dir / "parse"
    if parse_dir.exists():
        import shutil
        shutil.rmtree(parse_dir, ignore_errors=True)
        removed.append(str(parse_dir))

    try:
        # job root layout: .../runs/<job_id>/{input,parse,extract,...}
        run_parent = run_dir.parent
        input_dir = run_parent / "input"
        if input_dir.exists():
            import shutil
            shutil.rmtree(input_dir, ignore_errors=True)
            removed.append(str(input_dir))
    except Exception:
        pass

    # Best-effort fallback if input path still exists outside input_dir.
    try:
        if input_pdf.exists():
            input_pdf.unlink(missing_ok=True)
            removed.append(str(input_pdf))
    except Exception:
        pass

    return {"cleanup_enabled": True, "removed": removed}


def _purge_job_workspace(*, run_dir: Path, enabled: bool) -> dict[str, Any]:
    """Delete whole job workspace (runs/<job_id>) after completion."""
    if not enabled:
        return {"purge_enabled": False, "purged": False, "job_root": str(run_dir.parent)}
    job_root = run_dir.parent
    try:
        import shutil
        shutil.rmtree(job_root, ignore_errors=True)
        return {"purge_enabled": True, "purged": True, "job_root": str(job_root)}
    except Exception as exc:
        return {"purge_enabled": True, "purged": False, "job_root": str(job_root), "error": str(exc)}


def _is_cancel_requested(store: JobStore, job_id: str) -> bool:
    row = store.get_job(job_id)
    return bool(row and row.get("requested_cancel"))


def _run_parse_pdf(job_id: str, input_pdf: Path, run_dir: Path, store: JobStore, options: dict[str, Any] | None = None) -> dict[str, Any]:
    _stage_update(store, job_id, "parse_pdf", 5, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        raise RuntimeError("job_cancelled")

    # Merge injected settings on top of stored options
    merged = dict(options or {})
    opts_raw = store.get_job(job_id) or {}
    raw_options = str(opts_raw.get("options_json", "") or "").strip()
    if raw_options:
        try:
            obj = json.loads(raw_options)
            if isinstance(obj, dict):
                merged = {**obj, **merged}
        except Exception:
            pass

    def _progress(pct: int, _label: str) -> None:
        _stage_update(store, job_id, "parse_pdf", max(5, min(45, int(pct))), "stage_progress", status="running")

    def _cancel() -> bool:
        return _is_cancel_requested(store, job_id)

    try:
        meta = parse_single_pdf(
            input_pdf,
            run_dir,
            options=merged,
            progress_cb=_progress,
            cancel_cb=_cancel,
        )
    except Exception as exc:
        code = getattr(exc, "code", "")
        if str(code) == "job_cancelled":
            raise RuntimeError("job_cancelled")
        if str(code):
            raise RuntimeError(f"{code}:{getattr(exc, 'detail', str(exc))}")
        raise
    _stage_update(store, job_id, "parse_pdf", 45, "stage_done", status="running")
    return meta


def _build_llm_client(options: dict[str, Any]) -> Any:
    provider = str(options.get("llm_provider", "")).strip().lower() or None
    model = str(options.get("llm_model", "")).strip() or None
    provider_options = {
        "api_key_env": str(options.get("llm_api_key_env", "")).strip() or None,
        "base_url": str(options.get("llm_base_url", "")).strip() or None,
        "api_key": str(options.get("llm_api_key", "")).strip() or None,
        "timeout_seconds": options.get("llm_timeout_seconds"),
        "temperature": options.get("llm_temperature"),
        "max_tokens": options.get("llm_max_tokens"),
        "max_retries": options.get("llm_max_retries"),
    }
    provider_options = {k: v for k, v in provider_options.items() if v not in (None, "")}
    try:
        registry = ProviderRegistry()
        return registry.create_extraction_client(
            provider=provider,
            model=model,
            options=provider_options,
        )
    except Exception:
        return NullLLMClient()


def _run_agent_extraction(job_id: str, parse_meta: dict[str, Any], run_dir: Path, store: JobStore, options: dict[str, Any]) -> dict[str, Any]:
    """Run extraction via agent (Codex/Claude Code/Gemini CLI) with scholarly-paper-extraction skill."""
    _stage_update(store, job_id, "extract_entities", 55, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "extract_entities"})
        raise RuntimeError("job_cancelled")

    agent_md_path_raw = str(options.get("_materialized_md_path", "") or "").strip()
    if agent_md_path_raw:
        agent_md_path = Path(agent_md_path_raw).resolve()
    else:
        agent_md_path = Path(str(parse_meta.get("markdown_path", ""))).resolve()
    if not agent_md_path.exists():
        raise RuntimeError(f"missing_markdown_for_extraction:{agent_md_path}")
    html_path = Path(str(parse_meta.get("html_path", ""))).resolve()

    extract_dir = run_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    event_log_path = _agent_event_log_path(run_dir)
    raw_output_path = extract_dir / "raw_llm_outputs.jsonl"
    review_queue_path = extract_dir / "review_queue.jsonl"
    report_path = extract_dir / "acceptance_report.md"

    # Resolve library_id
    library_id = str(options.get("library_id", "") or "").strip()
    if not library_id:
        raise RuntimeError("agent_extraction_failed:library_id_required")

    # Find the library workspace path (parent of corpus/papers/).
    # Fall back to _workspace_path from options for new libraries that have
    # no papers imported yet (corpus/papers/ doesn't exist).
    html_resolved = html_path
    workspace_path = ""
    for ancestor in html_resolved.parents:
        if (ancestor / "corpus" / "papers").is_dir():
            workspace_path = str(ancestor)
            break
    if not workspace_path:
        workspace_path = str(options.get("_workspace_path", "") or "").strip()
    if not workspace_path:
        raise RuntimeError(f"agent_extraction_failed:cannot_resolve_workspace_from:{html_path}")
    try:
        from kn_graph.services.agent_workspace_guard import ensure_agent_workspace_minimal_config
        ensure_agent_workspace_minimal_config(
            workspace_path,
            "pipeline_library",
            library_id=library_id,
        )
    except Exception as exc:
        raise RuntimeError(f"agent_workspace_config_invalid:{exc}") from exc

    # Build agent config from options
    backend = str(options.get("pipeline_agent_backend", "codex") or "codex").strip().lower()
    if backend not in ("codex", "claude_code", "gemini_cli"):
        backend = "codex"

    agent_config = {
        "provider": str(options.get("pipeline_agent_provider", "") or "").strip(),
        "model": str(options.get("pipeline_agent_model", "") or "").strip(),
        "api_key": str(options.get("pipeline_agent_api_key", "") or "").strip(),
        "base_url": str(options.get("pipeline_agent_base_url", "") or "").strip(),
        "reasoning_effort": str(options.get("pipeline_agent_reasoning_effort", "") or "").strip().lower(),
    }
    agent_config = {k: v for k, v in agent_config.items() if v}

    # Write agent config to {data_dir}/chat/{backend}_config.json
    global _pipeline_settings
    config_dir = (_pipeline_settings.data_dir / "chat") if _pipeline_settings else (Path.home() / ".kn_graph" / "chat")
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{backend}_config.json"
    # Merge with existing if present
    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}
    existing.update(agent_config)
    config_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    # Ensure skills are deployed to .claude/skills/ and .agents/skills/.
    # bootstrap_workspace_project_skills is idempotent — it overwrites with
    # the latest template content on every call, so skill updates propagate
    # automatically. Both Claude Code and Codex auto-discover skills from
    # these convention paths, so no explicit project_skills override is needed.
    from kn_graph.services.codex_library_config import bootstrap_workspace_project_skills as _deploy_skills
    _deploy_skills(workspace_path, skill_names=["scholarly-paper-extraction"])

    # Build runner
    codex_config_path = config_dir / "codex_runner_config.json"
    from kn_graph.services.agent_runner import AgentRunnerFactory
    factory = AgentRunnerFactory(codex_config_path=codex_config_path)
    runner = factory.build(backend)

    # Build runtime_overrides
    mcp_server_script = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline" / "kn_mcp_server.py"
    runtime_overrides = {
        "mcp_servers": [
            {
                "name": "kn_graph_tools",
                "command": "uv",
                "args": ["run", "python", str(mcp_server_script)],
                "env": {},
            }
        ],
    }

    # Build extraction prompt
    extraction_prompt = (
        f"请按照 scholarly-paper-extraction skill 处理以下论文。\n\n"
        f"论文 markdown 路径: {agent_md_path}\n"
        f"library_id: {library_id}\n"
        f"输出目录: {extract_dir}\n"
        f"工作区路径: {workspace_path}\n\n"
        f"请完成三步流程后将最终结构化结果写入 {extract_dir / 'extract_result.json'}"
    )

    _stage_update(store, job_id, "extract_entities", 60, "agent_running", status="running")

    # Call agent with timeout
    agent_timeout_seconds = int(os.getenv("PIPELINE_AGENT_TURN_TIMEOUT_SECONDS", "1200") or "1200")
    if agent_timeout_seconds < 60:
        agent_timeout_seconds = 60
    try:
        event_seq = 0

        # Persist full invocation context for audit/debug.
        input_event = {
            "method": "pipeline/agent_input",
            "params": {
                "library_id": library_id,
                "workspace_path": workspace_path,
                "markdown_path": str(agent_md_path),
                "extract_dir": str(extract_dir),
                "query": extraction_prompt,
            },
        }
        event_seq += 1
        saved_input = _append_agent_event(
            log_path=event_log_path,
            seq=event_seq,
            job_id=job_id,
            backend=backend,
            event=input_event,
        )
        if hasattr(store, "append_agent_event") and isinstance(saved_input, dict):
            try:
                store.append_agent_event(job_id, saved_input)
            except Exception:
                pass

        def _on_agent_event(evt: dict[str, Any]) -> None:
            nonlocal event_seq
            event_seq += 1
            try:
                saved = _append_agent_event(
                    log_path=event_log_path,
                    seq=event_seq,
                    job_id=job_id,
                    backend=backend,
                    event=evt if isinstance(evt, dict) else {"method": "unknown", "params": {"raw": str(evt)}},
                )
                if hasattr(store, "append_agent_event") and isinstance(saved, dict):
                    try:
                        store.append_agent_event(job_id, saved)
                    except Exception:
                        pass
            except Exception:
                pass

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(
                runner.run_turn,
                query=extraction_prompt,
                workdir=workspace_path,
                library_id=library_id,
                thread_id="",
                runtime_overrides=runtime_overrides,
                on_event=_on_agent_event,
            )
            result = fut.result(timeout=agent_timeout_seconds)
    except Exception as exc:
        raise RuntimeError(f"agent_extraction_failed:{backend}:{exc}") from exc

    _stage_update(store, job_id, "extract_entities", 85, "agent_done_reading_result", status="running")

    # Read agent output
    extract_result_path = extract_dir / "extract_result.json"
    if not extract_result_path.exists():
        raise RuntimeError("agent_extraction_failed:missing_extract_result_json")

    try:
        agent_bundle = json.loads(extract_result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"agent_extraction_failed:invalid_extract_result_json:{exc}") from exc

    _ensure_reader_note_written(agent_md_path, job_id, agent_bundle if isinstance(agent_bundle, dict) else {})

    # Convert agent bundle to raw_output_jsonl format for downstream compatibility
    paper_id = str(options.get("paper_id", "") or f"job::{job_id}").strip()
    doi = str(options.get("doi", "") or f"job::{job_id}").strip()
    extracted_meta = _extract_agent_paper_metadata(agent_bundle)
    raw_record = {
        "paper_id": paper_id,
        "doi": extracted_meta.get("doi") or doi,
        "status": "ok",
        "evidence_spans": 1,
        "paper_domains": agent_bundle.get("paper_domains", []),
        "title": extracted_meta.get("title", ""),
        "authors_json": extracted_meta.get("authors_json", []),
        "abstract": extracted_meta.get("abstract", ""),
        "journal": extracted_meta.get("journal", ""),
        "publication_date": extracted_meta.get("publication_date", ""),
        "online_date": extracted_meta.get("online_date", ""),
        "publication_year": extracted_meta.get("publication_year"),
        "article_url": extracted_meta.get("article_url", ""),
        "raw_response": json.dumps(agent_bundle, ensure_ascii=False),
    }
    raw_output_path.write_text(json.dumps(raw_record, ensure_ascii=False) + "\n", encoding="utf-8")

    # Build compatible payload for _run_finalize
    summary = {
        "seen": 1,
        "class_a_used": 1,
        "class_b_skipped": 0,
        "class_c_skipped": 0,
        "denominator_used": 1,
    }
    metrics = {
        "extractable_rate": 1.0,
        "mean_direct_effects_per_doc": float(len(agent_bundle.get("direct_effects", []))),
        "mean_moderations_per_doc": float(len(agent_bundle.get("moderations", []))),
        "mean_interactions_per_doc": float(len(agent_bundle.get("interactions", []))),
        "direct_effect_validation_rate": 1.0,
    }
    payload = {
        "summary": summary,
        "metrics": metrics,
        "report_path": str(report_path),
        "raw_output_jsonl": str(raw_output_path),
        "review_queue_jsonl": str(review_queue_path),
    }
    # Overwrite extract_result.json with the pipeline-compatible payload format
    (extract_dir / "extract_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _stage_update(store, job_id, "extract_entities", 90, "stage_done", status="running")
    return payload


def _run_extract_entities(job_id: str, parse_meta: dict[str, Any], run_dir: Path, store: JobStore, options: dict[str, Any]) -> dict[str, Any]:
    mode = str(options.get("extraction_mode", "fast") or "fast").strip().lower()
    if mode == "agent":
        return _run_agent_extraction(job_id, parse_meta, run_dir, store, options)
    return _run_extract_entities_fast(job_id, parse_meta, run_dir, store, options)


def _run_extract_entities_fast(job_id: str, parse_meta: dict[str, Any], run_dir: Path, store: JobStore, options: dict[str, Any]) -> dict[str, Any]:
    _stage_update(store, job_id, "extract_entities", 55, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "extract_entities"})
        raise RuntimeError("job_cancelled")

    html_path = Path(str(parse_meta.get("html_path", "")))
    if not html_path.exists():
        raise RuntimeError(f"missing_html_for_extraction:{html_path}")

    extract_dir = run_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    raw_output_path = extract_dir / "raw_llm_outputs.jsonl"
    review_queue_path = extract_dir / "review_queue.jsonl"
    report_path = extract_dir / "acceptance_report.md"

    row = {"paper_id": job_id, "doi": f"job::{job_id}", "html": html_path.read_text(encoding="utf-8", errors="ignore")}
    client = _build_llm_client(options)
    artifacts = run_extraction_mvp(
        [row],
        sample_size=1,
        llm_client=client,
        project_root=Path.cwd(),
        review_queue_jsonl=review_queue_path,
        report_output_path=report_path,
        raw_output_jsonl=raw_output_path,
    )
    summary = artifacts.summary.to_dict()
    payload = {
        "summary": summary,
        "metrics": artifacts.metrics,
        "report_path": str(report_path),
        "raw_output_jsonl": str(raw_output_path),
        "review_queue_jsonl": str(review_queue_path),
    }
    (extract_dir / "extract_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _stage_update(store, job_id, "extract_entities", 90, "stage_done", status="running")
    return payload


def _run_materialize_import(
    job_id: str,
    input_pdf: Path,
    parse_meta: dict[str, Any],
    run_dir: Path,
    store: JobStore,
    options: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    _stage_update(store, job_id, "materialize_paper", 50, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "materialize_paper"})
        raise RuntimeError("job_cancelled")

    library_id = str(options.get("library_id", "") or "").strip()
    workspace_path = str(options.get("_workspace_path", "") or "").strip()
    import_result: dict[str, Any] = {}

    if library_id:
        try:
            _stage_update(store, job_id, "materialize_paper", 53, "stage_progress", status="running")
            from kn_graph.services.literature_service import LiteratureService
            literature = LiteratureService(settings=_pipeline_settings)
            manifest_path = run_dir / "import_manifest.jsonl"
            paper_id = str(options.get("paper_id", "") or f"job::{job_id}").strip()
            doi = str(options.get("doi", "") or f"job::{job_id}").strip()
            title = str(options.get("title", "") or input_pdf.stem or job_id).strip()
            parsed_html = parse_meta.get("html_path", "") or ""
            row = {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "offline_html_path": str(parsed_html),
                "source_path": str(input_pdf.resolve()),
            }
            manifest_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            import_result = literature.import_manifest(manifest_path=manifest_path, options={"library_id": library_id})
            workspace_path = str(import_result.get("workspace_path", "") or workspace_path)
        except Exception as exc:
            raise RuntimeError(f"import_failed:{exc}") from exc
    else:
        raise RuntimeError("import_failed:library_id_missing")

    _stage_update(store, job_id, "materialize_paper", 54, "stage_done", status="running")
    return import_result, workspace_path, library_id


def _run_finalize_after_import(
    job_id: str,
    input_pdf: Path,
    parse_meta: dict[str, Any],
    extract_result: dict[str, Any],
    run_dir: Path,
    store: JobStore,
    options: dict[str, Any],
    import_result: dict[str, Any],
    workspace_path: str,
    library_id: str,
    imported_count: int,
) -> dict[str, Any]:
    _stage_update(store, job_id, "finalize", 95, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "finalize"})
        raise RuntimeError("job_cancelled")

    import_warning = ""
    graph_warning = ""
    graph_output_path = ""
    graph_updated = False
    graph_output_size = 0
    if workspace_path:
        try:
            import sqlite3 as _sqlite3
            import json as _json
            db_path = Path(workspace_path) / "kn_gragh.db"
            conn = _sqlite3.connect(str(db_path))
            repo = SqliteRepo(conn)
            repo.apply_schema()

            mats = import_result.get("materialized_papers", []) or []
            mat0 = mats[0] or {} if mats else {}
            mat_paper_key = str(mat0.get("paper_key", "")).strip()
            mat_pdf_path = str(mat0.get("source_pdf_path", "") or "")
            mat_md_path = str(mat0.get("md_library_path", "") or "")
            mat_html_path = str(mat0.get("html_path", "") or "")

            raw_jsonl = run_dir / "extract" / "raw_llm_outputs.jsonl"
            if raw_jsonl.exists():
                mats_list = import_result.get("materialized_papers", []) or []
                mat_paper_key = str((mats_list[0] or {}).get("paper_key", "") if mats_list else "").strip()
                if mat_paper_key:
                    fixed_path = run_dir / "extract" / "raw_llm_outputs_fixed.jsonl"
                    with open(raw_jsonl, "r", encoding="utf-8") as fin, open(str(fixed_path), "w", encoding="utf-8") as fout:
                        for line in fin:
                            line = line.strip()
                            if not line:
                                continue
                            obj = json.loads(line)
                            obj["paper_id"] = mat_paper_key
                            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    raw_jsonl = fixed_path
                _stage_update(store, job_id, "finalize", 98, "importing_to_sqlite", status="running")
                _import_sqlite_main_inline(
                    db_path=str(db_path),
                    raw_output_jsonl=raw_jsonl,
                    apply_schema=False,
                    source_pdf_path=mat_pdf_path,
                    source_md_path=mat_md_path,
                    source_html_path=mat_html_path,
                )
            cur = conn.cursor()
            for m in mats:
                if not isinstance(m, dict):
                    continue
                pid = str(m.get("paper_id", "") or m.get("paper_key", "") or "").strip()
                if not pid:
                    continue
                meta_path = Path(str(m.get("meta_path", "") or ""))
                meta = {}
                if meta_path.exists():
                    try:
                        meta = _json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                title = str(meta.get("title", "") or "").strip() or str(m.get("title", "") or str(m.get("paper_key", "")) or "").strip()
                md_dir = Path(str(m.get("md_library_path", "") or m.get("md_path", "") or ""))
                md_full = md_dir / "full.md" if md_dir.is_dir() else md_dir
                cite_meta = _citation_metadata_from_markdown(md_full)
                doi = str(m.get("doi", "") or cite_meta.get("doi", "") or "").strip()
                authors_json = cite_meta.get("authors_json", [])
                journal = str(cite_meta.get("journal", "") or "").strip()
                publication_date = str(cite_meta.get("publication_date", "") or "").strip()
                publication_year = cite_meta.get("publication_year")
                cur.execute(
                    """UPDATE papers SET doi = ?, title = ?, authors_json = ?, journal = ?, publication_date = ?, publication_year = ?,
                       offline_html_path = ?, source_pdf_path = ?, source_md_path = ?,
                       source_html_path = ?, metadata_source = ?
                       WHERE paper_id = ?""",
                    (
                        doi,
                        title,
                        json.dumps(authors_json, ensure_ascii=False),
                        journal,
                        publication_date,
                        publication_year,
                        str(m.get("html_path", "") or ""),
                        str(m.get("source_pdf_path", "") or ""),
                        str(m.get("md_library_path", "") or m.get("md_path", "") or ""),
                        str(m.get("html_path", "") or ""),
                        "literature_import",
                        pid,
                    ),
                )
            conn.commit()
            conn.close()
            _stage_update(store, job_id, "finalize", 99, "building_graph_views", status="running")
            artifact = _build_artifact_from_sqlite(db_path)
            views_out = Path(workspace_path) / "graph_views.json"
            run_build_from_artifact(artifact, views_out)
            graph_output_path = str(views_out.resolve())
            graph_updated = views_out.exists()
            if graph_updated:
                graph_output_size = views_out.stat().st_size
        except Exception as exc:
            graph_warning = str(exc)

    keep_intermediates = bool(options.get("retain_job_intermediates", False))
    cleanup = _cleanup_redundant_job_files(
        input_pdf=input_pdf,
        run_dir=run_dir,
        keep_intermediates=keep_intermediates,
    )

    purge_job_workspace = bool(options.get("purge_job_workspace", True))
    result = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "library_id": library_id,
        "workspace_path": workspace_path,
        "parse": parse_meta,
        "extract": extract_result,
        "import_result": import_result,
        "import_warning": import_warning,
        "graph_warning": graph_warning,
        "imported_paper_count": imported_count,
        "graph_updated": bool(graph_updated),
        "graph_output_path": graph_output_path,
        "graph_output_size": int(graph_output_size),
        "cleanup": cleanup,
        "purge_job_workspace": {"enabled": purge_job_workspace},
        "final_verdict": "success",
        "finished_at": _now_iso(),
    }
    out_path = run_dir / "result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store.update_job(
        job_id,
        {
            "status": "completed",
            "stage": "finalize",
            "progress": 100,
            "output_path": str(out_path),
            "result_json": _safe_json_dumps(result),
            "last_event": "completed",
        },
    )
    purge = _purge_job_workspace(run_dir=run_dir, enabled=purge_job_workspace)
    if purge.get("purged"):
        store.update_job(job_id, {"output_path": "", "result_json": _safe_json_dumps({**result, "purge_job_workspace": purge})})
    else:
        store.update_job(job_id, {"result_json": _safe_json_dumps({**result, "purge_job_workspace": purge})})
    return result


def _run_finalize(
    job_id: str,
    input_pdf: Path,
    parse_meta: dict[str, Any],
    extract_result: dict[str, Any],
    run_dir: Path,
    store: JobStore,
    options: dict[str, Any],
) -> dict[str, Any]:
    _stage_update(store, job_id, "finalize", 95, "stage_started", status="running")
    if _is_cancel_requested(store, job_id):
        store.update_job(job_id, {"status": "cancelled", "last_event": "cancelled", "stage": "finalize"})
        raise RuntimeError("job_cancelled")

    library_id = str(options.get("library_id", "") or "").strip()
    workspace_path = str(options.get("_workspace_path", "") or "").strip()
    import_result: dict[str, Any] = {}
    import_warning = ""
    graph_output_path = ""
    graph_updated = False
    graph_output_size = 0
    if library_id:
        try:
            _stage_update(store, job_id, "finalize", 97, "stage_progress", status="running")
            from kn_graph.services.literature_service import LiteratureService
            literature = LiteratureService(settings=_pipeline_settings)
            manifest_path = run_dir / "import_manifest.jsonl"
            paper_id = str(options.get("paper_id", "") or f"job::{job_id}").strip()
            doi = str(options.get("doi", "") or f"job::{job_id}").strip()
            title = str(options.get("title", "") or input_pdf.stem or job_id).strip()
            parsed_html = parse_meta.get("html_path", "") or ""
            row = {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "offline_html_path": str(parsed_html),
                "source_path": str(input_pdf.resolve()),
            }
            manifest_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            import_result = literature.import_manifest(manifest_path=manifest_path, options={"library_id": library_id})
            workspace_path = str(import_result.get("workspace_path", "") or workspace_path)
        except Exception as exc:
            import_warning = str(exc)
            raise RuntimeError(f"import_failed:{import_warning}") from exc
    else:
        raise RuntimeError("import_failed:library_id_missing")

    imported_count = int(import_result.get("imported_count", 0) or 0)
    if imported_count <= 0:
        raise RuntimeError("import_noop:imported_count_is_zero")

    # ── Persist paper metadata to SQLite from import result ──
    graph_warning = ""
    graph_output_path = ""
    graph_updated = False
    graph_output_size = 0
    if workspace_path:
        try:
            import sqlite3 as _sqlite3
            import json as _json
            db_path = Path(workspace_path) / "kn_gragh.db"
            conn = _sqlite3.connect(str(db_path))
            repo = SqliteRepo(conn)
            repo.apply_schema()

            mats = import_result.get("materialized_papers", []) or []
            mat_paper_key = str((mats[0] or {}).get("paper_key", "") if mats else "").strip()

            # Import extraction results into SQLite first (writes paper metadata + variables)
            raw_jsonl = run_dir / "extract" / "raw_llm_outputs.jsonl"
            if raw_jsonl.exists():
                # Align extraction paper_id with the materialized paper_key from import
                # so extraction data and file paths reference the same paper record.
                mats_list = import_result.get("materialized_papers", []) or []
                mat_paper_key = str((mats_list[0] or {}).get("paper_key", "") if mats_list else "").strip()
                if mat_paper_key:
                    fixed_path = run_dir / "extract" / "raw_llm_outputs_fixed.jsonl"
                    with open(raw_jsonl, "r", encoding="utf-8") as fin, open(str(fixed_path), "w", encoding="utf-8") as fout:
                        for line in fin:
                            line = line.strip()
                            if not line:
                                continue
                            obj = json.loads(line)
                            obj["paper_id"] = mat_paper_key
                            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    raw_jsonl = fixed_path
                _stage_update(store, job_id, "finalize", 98, "importing_to_sqlite", status="running")
                _import_sqlite_main_inline(db_path=str(db_path), raw_output_jsonl=raw_jsonl, apply_schema=False)
            # Write paper file paths (UPDATE to preserve extraction metadata)
            cur = conn.cursor()
            for m in mats:
                if not isinstance(m, dict):
                    continue
                pid = str(m.get("paper_id", "") or m.get("paper_key", "") or "").strip()
                if not pid:
                    continue
                meta_path = Path(str(m.get("meta_path", "") or ""))
                meta = {}
                if meta_path.exists():
                    try:
                        meta = _json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                title = str(meta.get("title", "") or "").strip() or str(m.get("title", "") or str(m.get("paper_key", "")) or "").strip()
                md_dir = Path(str(m.get("md_library_path", "") or m.get("md_path", "") or ""))
                md_full = md_dir / "full.md" if md_dir.is_dir() else md_dir
                cite_meta = _citation_metadata_from_markdown(md_full)
                doi = str(m.get("doi", "") or cite_meta.get("doi", "") or "").strip()
                authors_json = cite_meta.get("authors_json", [])
                journal = str(cite_meta.get("journal", "") or "").strip()
                publication_date = str(cite_meta.get("publication_date", "") or "").strip()
                publication_year = cite_meta.get("publication_year")
                # Use UPDATE to avoid clearing extraction fields (extractability etc.)
                cur.execute(
                    """UPDATE papers SET doi = ?, title = ?, authors_json = ?, journal = ?, publication_date = ?, publication_year = ?,
                       offline_html_path = ?, source_pdf_path = ?, source_md_path = ?,
                       source_html_path = ?, metadata_source = ?
                       WHERE paper_id = ?""",
                    (
                        doi,
                        title,
                        json.dumps(authors_json, ensure_ascii=False),
                        journal,
                        publication_date,
                        publication_year,
                        str(m.get("html_path", "") or ""),
                        str(m.get("source_pdf_path", "") or ""),
                        str(m.get("md_library_path", "") or m.get("md_path", "") or ""),
                        str(m.get("html_path", "") or ""),
                        "literature_import",
                        pid,
                    ),
                )
            conn.commit()
            conn.close()
            # Always rebuild graph_views — paper metadata is now in SQLite
            _stage_update(store, job_id, "finalize", 99, "building_graph_views", status="running")
            artifact = _build_artifact_from_sqlite(db_path)
            views_out = Path(workspace_path) / "graph_views.json"
            run_build_from_artifact(artifact, views_out)
            graph_output_path = str(views_out.resolve())
            graph_updated = views_out.exists()
            if graph_updated:
                graph_output_size = views_out.stat().st_size
        except Exception as exc:
            graph_warning = str(exc)

    keep_intermediates = bool(options.get("retain_job_intermediates", False))
    cleanup = _cleanup_redundant_job_files(
        input_pdf=input_pdf,
        run_dir=run_dir,
        keep_intermediates=keep_intermediates,
    )

    purge_job_workspace = bool(options.get("purge_job_workspace", True))
    result = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "library_id": library_id,
        "workspace_path": workspace_path,
        "parse": parse_meta,
        "extract": extract_result,
        "import_result": import_result,
        "import_warning": import_warning,
        "graph_warning": graph_warning,
        "imported_paper_count": imported_count,
        "graph_updated": bool(graph_updated),
        "graph_output_path": graph_output_path,
        "graph_output_size": int(graph_output_size),
        "cleanup": cleanup,
        "purge_job_workspace": {"enabled": purge_job_workspace},
        "final_verdict": "success",
        "finished_at": _now_iso(),
    }
    out_path = run_dir / "result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store.update_job(
        job_id,
        {
            "status": "completed",
            "stage": "finalize",
            "progress": 100,
            "output_path": str(out_path),
            "result_json": _safe_json_dumps(result),
            "last_event": "completed",
        },
    )
    purge = _purge_job_workspace(run_dir=run_dir, enabled=purge_job_workspace)
    if purge.get("purged"):
        store.update_job(job_id, {"output_path": "", "result_json": _safe_json_dumps({**result, "purge_job_workspace": purge})})
    else:
        store.update_job(job_id, {"result_json": _safe_json_dumps({**result, "purge_job_workspace": purge})})
    return result


_pipeline_settings: Any = None


def init_pipeline_settings(settings: Any) -> None:
    global _pipeline_settings
    _pipeline_settings = settings


def _inject_pipeline_settings(options: dict[str, Any]) -> dict[str, Any]:
    """Read pipeline settings from the Settings object and inject into options."""
    global _pipeline_settings
    settings = _pipeline_settings
    out = dict(options)

    if settings is None:
        if not out.get("llm_timeout_seconds"):
            out["llm_timeout_seconds"] = 300
        return out

    # mineru_api_key — this was missing before, causing the 5% failure
    if not str(out.get("mineru_api_key", "") or "").strip():
        val = str(getattr(settings, "mineru_api_key", "") or "").strip()
        if val:
            out["mineru_api_key"] = val

    # LLM provider / model / key from pipeline extraction settings
    if not str(out.get("llm_provider", "") or "").strip():
        val = str(getattr(settings, "pipeline_fast_provider", "") or "").strip()
        if val:
            out["llm_provider"] = val

    if not str(out.get("llm_model", "") or "").strip():
        val = str(getattr(settings, "pipeline_fast_model", "") or "").strip()
        if val:
            out["llm_model"] = val

    if not str(out.get("llm_api_key", "") or "").strip():
        val = str(getattr(settings, "deepseek_api_key", "") or "").strip()
        if val:
            out["llm_api_key"] = val

    if not str(out.get("llm_base_url", "") or "").strip():
        val = str(getattr(settings, "pipeline_fast_endpoint_url", "") or "").strip()
        if val:
            out["llm_base_url"] = val

    if not out.get("llm_timeout_seconds"):
        out["llm_timeout_seconds"] = 300

    # Whether to keep duplicated job-level parse/input intermediates after success.
    # Default false: keep corpus/papers as the single long-term source of files.
    if "retain_job_intermediates" not in out:
        out["retain_job_intermediates"] = str(
            os.getenv("KN_PIPELINE_RETAIN_JOB_INTERMEDIATES", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

    # Whether to remove whole runs/<job_id> after successful finalize.
    # Default on: jobs are transient runtime state, corpus/papers is the sole long-term asset.
    if "purge_job_workspace" not in out:
        out["purge_job_workspace"] = str(
            os.getenv("KN_PIPELINE_PURGE_JOB_WORKSPACE", "1")
        ).strip().lower() in {"1", "true", "yes", "on"}

    # extraction_mode
    if not str(out.get("extraction_mode", "") or "").strip():
        val = str(getattr(settings, "pipeline_extraction_mode", "fast") or "fast").strip()
        out["extraction_mode"] = val

    # pipeline_agent_backend
    if not str(out.get("pipeline_agent_backend", "") or "").strip():
        val = str(getattr(settings, "pipeline_agent_backend", "codex") or "codex").strip()
        out["pipeline_agent_backend"] = val

    # pipeline_agent_provider
    if not str(out.get("pipeline_agent_provider", "") or "").strip():
        val = str(getattr(settings, "pipeline_agent_provider", "") or "").strip()
        if val:
            out["pipeline_agent_provider"] = val

    # pipeline_agent_model
    if not str(out.get("pipeline_agent_model", "") or "").strip():
        val = str(getattr(settings, "pipeline_agent_model", "") or "").strip()
        if val:
            out["pipeline_agent_model"] = val

    # pipeline_agent_api_key
    if not str(out.get("pipeline_agent_api_key", "") or "").strip():
        val = str(getattr(settings, "pipeline_agent_api_key", "") or "").strip()
        if val:
            out["pipeline_agent_api_key"] = val

    # pipeline_agent_base_url
    if not str(out.get("pipeline_agent_base_url", "") or "").strip():
        val = str(getattr(settings, "pipeline_agent_base_url", "") or "").strip()
        if val:
            out["pipeline_agent_base_url"] = val

    # pipeline_agent_reasoning_effort
    if not str(out.get("pipeline_agent_reasoning_effort", "") or "").strip():
        val = str(getattr(settings, "pipeline_agent_reasoning_effort", "") or "").strip().lower()
        if val:
            out["pipeline_agent_reasoning_effort"] = val

    return out


def execute_pipeline(job_store: JobStore, job_id: str, input_path: str, options: dict[str, Any], runs_root: Path) -> None:
    options = _inject_pipeline_settings(options)
    job_root_raw = str(options.get("_job_root", "") or "").strip()
    run_dir = (Path(job_root_raw).resolve() / "run") if job_root_raw else (runs_root / job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    input_pdf = Path(input_path).resolve()
    try:
        parse_meta = _run_parse_pdf(job_id, input_pdf, run_dir, job_store, options)
        mode = str(options.get("extraction_mode", "fast") or "fast").strip().lower()
        if mode == "agent":
            import_result, workspace_path, library_id = _run_materialize_import(
                job_id=job_id,
                input_pdf=input_pdf,
                parse_meta=parse_meta,
                run_dir=run_dir,
                store=job_store,
                options=options,
            )
            imported_count = int(import_result.get("imported_count", 0) or 0)
            if imported_count <= 0:
                raise RuntimeError("import_noop:imported_count_is_zero")
            mats = import_result.get("materialized_papers", []) or []
            mat0 = mats[0] if isinstance(mats, list) and mats else {}
            materialized_md_path = str((mat0 or {}).get("md_library_path", "") or "").strip()
            options = dict(options)
            options["_workspace_path"] = workspace_path
            options["_materialized_md_path"] = materialized_md_path
            extract_result = _run_agent_extraction(job_id, parse_meta, run_dir, job_store, options)
            _run_finalize_after_import(
                job_id=job_id,
                input_pdf=input_pdf,
                parse_meta=parse_meta,
                extract_result=extract_result,
                run_dir=run_dir,
                store=job_store,
                options=options,
                import_result=import_result,
                workspace_path=workspace_path,
                library_id=library_id,
                imported_count=imported_count,
            )
        else:
            extract_result = _run_extract_entities(job_id, parse_meta, run_dir, job_store, options)
            _run_finalize(job_id, input_pdf, parse_meta, extract_result, run_dir, job_store, options)
    except Exception as exc:
        if "job_cancelled" in str(exc):
            job_store.update_job(
                job_id,
                {"status": "cancelled", "stage": str((job_store.get_job(job_id) or {}).get("stage", "parse_pdf")), "last_event": "cancelled"},
            )
            return
        detail = str(exc)
        code = "pipeline_failed"
        if ":" in detail:
            first = detail.split(":", 1)[0].strip()
            if first:
                code = first
        cur = job_store.get_job(job_id) or {}
        failed_stage = str(cur.get("stage", "") or "unknown")
        job_store.update_job(
            job_id,
            {
                "status": "failed",
                "error_code": code,
                "error_detail": detail,
                "stage": failed_stage,
                "last_event": "failed",
                "result_json": _safe_json_dumps(
                    {
                        "job_id": job_id,
                        "final_verdict": "failed",
                        "failure_stage": failed_stage,
                        "failure_code": code,
                        "failure_detail": detail,
                        "finished_at": _now_iso(),
                    }
                ),
            },
        )


def dispatch_inline(job_store: JobStore, job_id: str, input_path: str, options: dict[str, Any], runs_root: Path) -> None:
    t = threading.Thread(target=execute_pipeline, args=(job_store, job_id, input_path, options, runs_root), daemon=True)
    t.start()

