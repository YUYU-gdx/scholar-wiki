from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterator

import requests


OPENAI_COMPAT_BASE = "https://open.bigmodel.cn/api/paas/v4"


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_run_full_batch", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, dict):
                yield obj


def _resolve_html(row: dict[str, Any], root: Path) -> str:
    html = str(row.get("html", "") or "")
    if html.strip():
        return html
    for key in ("offline_html_path", "raw_html_path", "html_path", "full_html_path"):
        value = str(row.get(key, "") or "").strip()
        if not value:
            continue
        p = Path(value)
        if not p.is_absolute():
            p = root / p
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def _build_body(model: str, system_prompt: str, user_content: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "stream": False,
    }


def _write_jsonl_shards(
    rows: list[dict[str, Any]],
    out_dir: Path,
    max_shard_bytes: int,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    shard_paths: list[Path] = []
    idx = 1
    cur_bytes = 0
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal idx, cur_bytes, cur_lines
        if not cur_lines:
            return
        p = out_dir / f"batch_requests_part_{idx:03d}.jsonl"
        p.write_text("\n".join(cur_lines) + "\n", encoding="utf-8")
        shard_paths.append(p)
        idx += 1
        cur_bytes = 0
        cur_lines = []

    for row in rows:
        line = json.dumps(row, ensure_ascii=False)
        line_bytes = len(line.encode("utf-8")) + 1
        if cur_lines and cur_bytes + line_bytes > max_shard_bytes:
            flush()
        cur_lines.append(line)
        cur_bytes += line_bytes
    flush()
    return shard_paths


def _upload_file(api_key: str, path: Path) -> dict[str, Any]:
    url = f"{OPENAI_COMPAT_BASE}/files"
    headers = {"Authorization": f"Bearer {api_key}"}
    with path.open("rb") as f:
        files = {"file": (path.name, f, "application/jsonl")}
        data = {"purpose": "batch"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"upload failed status={r.status_code} body={r.text[:800]}")
    return r.json()


def _create_batch(api_key: str, input_file_id: str, endpoint: str = "/v4/chat/completions") -> dict[str, Any]:
    url = f"{OPENAI_COMPAT_BASE}/batches"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "input_file_id": input_file_id,
        "endpoint": endpoint,
        "auto_delete_input_file": False,
        "metadata": {"source": "smj-full-batch"},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"create batch failed status={r.status_code} body={r.text[:800]}")
    return r.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and submit full SMJ extraction to BigModel Batch API.")
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=Path("outputs/smj_extraction_mvp/manifest_from_success_nobom.jsonl"),
    )
    parser.add_argument("--model", default="glm-4.5")
    parser.add_argument("--api-key-env", default="ZHIPU_API_KEY")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/smj_batch_full"))
    parser.add_argument("--max-shard-mb", type=int, default=90, help="Max JSONL shard size in MB (must be < 100).")
    parser.add_argument("--submit", action="store_true", help="Upload shards and create batch tasks.")
    parser.add_argument(
        "--class-a-only",
        action="store_true",
        default=False,
        help="Only submit Class A fulltext rows (skip abstract+references-only docs).",
    )
    return parser.parse_args()


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    root = Path.cwd()

    prompts_mod = _load_module(
        "smj_pipeline_extraction_prompts_for_batch",
        root / "scripts" / "smj_pipeline" / "extraction" / "prompts.py",
    )
    qualifier_mod = _load_module(
        "smj_pipeline_extraction_qualifier_for_batch",
        root / "scripts" / "smj_pipeline" / "extraction" / "qualifier.py",
    )
    system_prompt = prompts_mod.load_system_prompt_template()

    prepared_rows: list[dict[str, Any]] = []
    skipped = 0
    class_a = 0
    class_b = 0
    class_c = 0
    for i, row in enumerate(_iter_jsonl(args.input_manifest), start=1):
        html = _resolve_html(row, root)
        if not html.strip():
            skipped += 1
            continue

        if args.class_a_only:
            doc_class = str(getattr(qualifier_mod.classify_document(html), "doc_class", "C"))
            if doc_class == "A":
                class_a += 1
            elif doc_class == "B":
                class_b += 1
                skipped += 1
                continue
            else:
                class_c += 1
                skipped += 1
                continue

        user_content = prompts_mod.build_user_content(html)
        if not user_content.strip():
            skipped += 1
            continue

        doi = str(row.get("doi", "")).strip()
        paper_id = str(row.get("paper_id") or doi or f"row-{i}")
        custom_id = f"{paper_id}__{i}"
        prepared_rows.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v4/chat/completions",
                "body": _build_body(args.model, system_prompt, user_content),
            }
        )

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    shards_dir = out_dir / "requests"
    shard_paths = _write_jsonl_shards(
        prepared_rows,
        shards_dir,
        max_shard_bytes=args.max_shard_mb * 1024 * 1024,
    )

    prepare_summary = {
        "prepared_requests": len(prepared_rows),
        "skipped_rows": skipped,
        "class_a_rows": class_a,
        "class_b_rows": class_b,
        "class_c_rows": class_c,
        "class_a_only": args.class_a_only,
        "input_manifest": str(args.input_manifest),
        "model": args.model,
        "shard_count": len(shard_paths),
        "request_shards": [str(p) for p in shard_paths],
    }
    (out_dir / "prepare_summary.json").write_text(
        json.dumps(prepare_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not args.submit:
        print(json.dumps({"phase": "prepared", **prepare_summary}, ensure_ascii=False, indent=2))
        return

    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"missing api key in env: {args.api_key_env}")

    submitted: list[dict[str, Any]] = []
    for shard in shard_paths:
        file_obj = _upload_file(api_key, shard)
        file_id = str(file_obj.get("id", "")).strip()
        if not file_id:
            raise RuntimeError(f"upload succeeded but no file id: {shard}")
        batch_obj = _create_batch(api_key, file_id)
        submitted.append(
            {
                "request_file": str(shard),
                "file_id": file_id,
                "batch_id": str(batch_obj.get("id", "")),
                "batch_status": str(batch_obj.get("status", "")),
                "batch_response": batch_obj,
            }
        )
        time.sleep(1.2)

    submit_summary = {
        "submitted_batches": len(submitted),
        "batches": submitted,
        "prepared_requests": len(prepared_rows),
        "skipped_rows": skipped,
        "class_a_rows": class_a,
        "class_b_rows": class_b,
        "class_c_rows": class_c,
        "class_a_only": args.class_a_only,
    }
    (out_dir / "submit_summary.json").write_text(
        json.dumps(submit_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps({"phase": "submitted", **submit_summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
