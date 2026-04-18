from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator

import requests


BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_materialize_batch", module_path)
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
            payload = json.loads(text)
            if isinstance(payload, dict):
                yield payload


def _extract_content(batch_row: dict[str, Any]) -> str:
    response = batch_row.get("response")
    if not isinstance(response, dict):
        return ""
    body = response.get("body")
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    msg = (choices[0] or {}).get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and materialize BigModel batch outputs.")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--api-key-env", default="ZHIPU_API_KEY")
    parser.add_argument(
        "--submitted-request-jsonl",
        type=Path,
        default=Path("outputs/smj_batch_full/requests/batch_requests_part_001_fixed_glm4plus.jsonl"),
    )
    parser.add_argument(
        "--original-request-jsonl",
        type=Path,
        default=Path("outputs/smj_batch_full/requests/batch_requests_part_001.jsonl"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/smj_batch_full"))
    return parser.parse_args()


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"missing api key: {args.api_key_env}")

    headers = {"Authorization": f"Bearer {api_key}"}
    status_url = f"{BASE_URL}/batches/{args.batch_id}"
    sr = requests.get(status_url, headers=headers, timeout=60)
    sr.raise_for_status()
    status = sr.json()
    output_file_id = str(status.get("output_file_id", "")).strip()
    if not output_file_id:
        raise RuntimeError("batch has no output_file_id yet")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest_batch_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    content_url = f"{BASE_URL}/files/{output_file_id}/content"
    cr = requests.get(content_url, headers=headers, timeout=600)
    cr.raise_for_status()
    raw_path = out_dir / "batch_results_raw.jsonl"
    raw_path.write_bytes(cr.content)

    # Build custom_id mapping from submitted request -> original request custom_id (which includes doi)
    custom_map: dict[str, dict[str, str]] = {}
    with args.submitted_request_jsonl.open("r", encoding="utf-8") as fs, args.original_request_jsonl.open("r", encoding="utf-8") as fo:
        for s_line, o_line in zip(fs, fo):
            s_obj = json.loads(s_line)
            o_obj = json.loads(o_line)
            new_id = str(s_obj.get("custom_id", "")).strip()
            old_id = str(o_obj.get("custom_id", "")).strip()
            paper_id = old_id.rsplit("__", 1)[0] if "__" in old_id else old_id
            custom_map[new_id] = {
                "paper_id": paper_id,
                "doi": paper_id,
                "original_custom_id": old_id,
            }

    extractor_mod = _load_module(
        "smj_pipeline_extraction_extractor_materialize",
        Path("scripts/smj_pipeline/extraction/extractor.py"),
    )

    raw_llm_out = out_dir / "raw_llm_outputs_from_batch.jsonl"
    review_queue_out = out_dir / "review_queue_from_batch.jsonl"
    parsed_ok = 0
    parsed_err = 0
    rows_total = 0

    with raw_llm_out.open("w", encoding="utf-8", newline="\n") as fw, review_queue_out.open("w", encoding="utf-8", newline="\n") as fq:
        for row in _iter_jsonl(raw_path):
            rows_total += 1
            custom_id = str(row.get("custom_id", "")).strip()
            meta = custom_map.get(custom_id, {})
            paper_id = meta.get("paper_id", custom_id)
            doi = meta.get("doi", paper_id)

            status_code = None
            response = row.get("response")
            if isinstance(response, dict):
                status_code = response.get("status_code")

            content = _extract_content(row)
            if str(status_code) != "200" or not content.strip():
                parsed_err += 1
                err = f"batch_status_code={status_code}"
                fw.write(json.dumps({"paper_id": paper_id, "doi": doi, "status": "error", "error": err}, ensure_ascii=False) + "\n")
                fq.write(json.dumps({"reason_codes": ["PROCESSING_ERROR"], "record": {"paper_id": paper_id, "doi": doi, "error": err}}, ensure_ascii=False) + "\n")
                continue

            try:
                # Validate parseability in current pipeline contract.
                extractor_mod.parse_extraction_response(content)
                parsed_ok += 1
                fw.write(
                    json.dumps(
                        {"paper_id": paper_id, "doi": doi, "status": "ok", "evidence_spans": None, "raw_response": content},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            except Exception as exc:  # noqa: BLE001
                parsed_err += 1
                err = str(exc)
                fw.write(json.dumps({"paper_id": paper_id, "doi": doi, "status": "error", "error": err}, ensure_ascii=False) + "\n")
                fq.write(json.dumps({"reason_codes": ["PROCESSING_ERROR"], "record": {"paper_id": paper_id, "doi": doi, "error": err}}, ensure_ascii=False) + "\n")

    summary = {
        "batch_id": args.batch_id,
        "output_file_id": output_file_id,
        "rows_total": rows_total,
        "parsed_ok": parsed_ok,
        "parsed_error": parsed_err,
        "batch_results_raw": str(raw_path),
        "raw_llm_outputs": str(raw_llm_out),
        "review_queue": str(review_queue_out),
    }
    (out_dir / "materialize_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
