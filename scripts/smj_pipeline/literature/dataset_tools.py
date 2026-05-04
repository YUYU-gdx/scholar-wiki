from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
import shutil

# Ensure the parent scripts directory is on sys.path so that module-level
# imports inside mineru_single_pdf_runner.py resolve correctly.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_MINERU_SINGLE_MOD = None


def _get_mineru_single_mod():
    """Lazy-load the mineru_single_pdf_runner module (cloud API)."""
    global _MINERU_SINGLE_MOD
    if _MINERU_SINGLE_MOD is None:
        module_path = Path(__file__).resolve().parent.parent / "mineru_single_pdf_runner.py"
        spec = importlib.util.spec_from_file_location("smj_pipeline_mineru_single_for_dataset_tools", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load module: {module_path}")
        _MINERU_SINGLE_MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MINERU_SINGLE_MOD)
    return _MINERU_SINGLE_MOD


_TAG_RE = re.compile(r"(?s)<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_DOI_PREFIX_RE = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_MOJIBAKE_RE = re.compile(r"[锟�ÃÂÐÑ¤¦�]+")


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, dict):
                rows.append(obj)
            elif isinstance(obj, list):
                rows.extend([x for x in obj if isinstance(x, dict)])
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_doi(doi: str) -> str:
    text = str(doi or "").strip()
    if not text:
        return ""
    text = _DOI_PREFIX_RE.sub("", text).strip().lower()
    return text


def resolve_source_path(row: dict[str, Any]) -> Path | None:
    for key in ("source_path", "offline_html_path", "raw_html_path", "html_path", "full_html_path", "file_path", "path"):
        val = str(row.get(key, "") or "").strip()
        if val:
            return Path(val)
    return None


def collect_input_rows(input_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not input_root.exists():
        return rows
    exts = {".pdf", ".html", ".htm", ".md", ".txt"}
    for path in input_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        doi_guess = _guess_doi_from_path(path)
        paper_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", path.stem)[:180] or path.stem
        rows.append(
            {
                "paper_id": paper_id,
                "doi": doi_guess,
                "source_path": str(path),
            }
        )
    return rows


def _guess_doi_from_path(path: Path) -> str:
    name = path.stem.replace("_", "/")
    if name.lower().startswith("10."):
        return name
    return ""


def normalize_to_html(
    row: dict[str, Any],
    normalized_dir: Path,
    max_source_bytes: int = 8_000_000,
) -> tuple[str, Path]:
    paper_id = str(row.get("paper_id") or row.get("doi") or "unknown").strip() or "unknown"
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", paper_id)[:180] or "unknown"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    out_html = normalized_dir / f"{safe_name}.html"

    inline_html = str(row.get("html", "") or "").strip()
    if inline_html:
        out_html.write_text(inline_html, encoding="utf-8")
        return inline_html, out_html

    source = resolve_source_path(row)
    if source is None:
        raise RuntimeError("missing_source_path")
    if not source.exists():
        raise RuntimeError(f"source_not_found:{source}")
    try:
        if int(source.stat().st_size) > int(max_source_bytes):
            raise RuntimeError(f"source_too_large:{source.stat().st_size}")
    except OSError:
        pass

    ext = source.suffix.lower()
    if ext in {".html", ".htm"}:
        data = source.read_text(encoding="utf-8", errors="ignore")
        out_html.write_text(data, encoding="utf-8")
        return data, out_html

    if ext == ".pdf":
        mineru_data, mineru_format = _pdf_to_html_with_mineru(source, "")
        if mineru_format == "html":
            out_html.write_text(mineru_data, encoding="utf-8")
            return mineru_data, out_html
        out_md = normalized_dir / f"{safe_name}.md"
        out_md.write_text(mineru_data, encoding="utf-8")
        return mineru_data, out_md

    if ext in {".md", ".txt"}:
        raw = source.read_text(encoding="utf-8", errors="ignore")
        return raw, source

    raw = source.read_text(encoding="utf-8", errors="ignore")
    return raw, source


def _pdf_to_html_with_mineru(source_path: Path, _mineru_cmd_template: str = "") -> tuple[str, str]:
    """Convert a PDF to HTML using the Mineru cloud API.

    The second parameter is kept for backward compatibility but is ignored
    (the cloud API is always used).
    """
    mod = _get_mineru_single_mod()
    with tempfile.TemporaryDirectory(prefix="literature_mineru_cloud_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        result = mod.parse_single_pdf(source_path, tmp_path, options={})
        html_path = Path(str(result.get("html_path", "") or ""))
        if not html_path.exists():
            raise RuntimeError("mineru_cloud_produced_no_html")
        return html_path.read_text(encoding="utf-8", errors="ignore"), "html"


def html_to_text(raw_html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def garble_metrics(text: str) -> dict[str, float]:
    n = max(len(text), 1)
    replacement = text.count("\ufffd") / n
    controls = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t") / n
    mojibake = sum(len(m.group(0)) for m in _MOJIBAKE_RE.finditer(text)) / n
    score = replacement + controls + mojibake
    return {
        "garble_score": float(score),
        "replacement_ratio": float(replacement),
        "control_ratio": float(controls),
        "mojibake_ratio": float(mojibake),
    }


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def estimate_embedding_cost(total_tokens: int, cny_per_million_tokens: float, budget_cny: float) -> dict[str, Any]:
    estimated = (float(total_tokens) / 1_000_000.0) * float(cny_per_million_tokens)
    return {
        "total_tokens": int(total_tokens),
        "cny_per_million_tokens": float(cny_per_million_tokens),
        "estimated_cost_cny": round(estimated, 6),
        "budget_cny": float(budget_cny),
        "within_budget": estimated <= float(budget_cny),
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    text = str(value).strip()
    if not text or text.upper() == "NULL":
        return float(default)
    try:
        return float(text)
    except ValueError:
        return float(default)


def build_base_dataset(
    manifest_path: Path | None,
    output_dir: Path,
    input_root: Path | None = None,
    garble_threshold: float = 0.02,
    cny_per_million_tokens: float = 2.0,
    budget_cny: float = 100.0,
    max_source_bytes: int = 8_000_000,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if manifest_path is not None:
        rows.extend(iter_jsonl(manifest_path))
    if input_root is not None:
        rows.extend(collect_input_rows(input_root))
    normalized_dir = output_dir / "normalized_html"
    base_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    seen_doi: set[str] = set()
    seen_hash: set[str] = set()
    total_tokens = 0

    for row in rows:
        paper_id = str(row.get("paper_id") or row.get("doi") or "").strip()
        doi = str(row.get("doi", "") or "").strip()
        doi_norm = normalize_doi(doi)
        source = resolve_source_path(row)
        reject_reason = ""
        normalized_path = ""
        text = ""
        text_hash = ""

        try:
            html_text, html_path = normalize_to_html(
                row=row,
                normalized_dir=normalized_dir,
                max_source_bytes=max_source_bytes,
            )
            normalized_path = str(html_path)
            text = html_to_text(html_text)
        except Exception as exc:  # noqa: BLE001
            reject_reason = _normalize_reject_reason(str(exc))

        if not reject_reason and not text:
            reject_reason = "empty_text"

        metrics = garble_metrics(text) if not reject_reason else {
            "garble_score": 0.0,
            "replacement_ratio": 0.0,
            "control_ratio": 0.0,
            "mojibake_ratio": 0.0,
        }
        if not reject_reason and float(metrics["garble_score"]) > float(garble_threshold):
            reject_reason = "garbled_text"

        if not reject_reason and doi_norm:
            if doi_norm in seen_doi:
                reject_reason = "duplicate_doi"
            else:
                seen_doi.add(doi_norm)

        if not reject_reason:
            text_hash = text_sha256(text)
            if text_hash in seen_hash:
                reject_reason = "duplicate_text_sha256"
            else:
                seen_hash.add(text_hash)

        payload = {
            "paper_id": paper_id,
            "doi": doi,
            "doi_norm": doi_norm,
            "source_path": str(source) if source else "",
            "normalized_html_path": normalized_path,
            "text_sha256": text_hash,
            "token_estimate": estimate_tokens(text) if text else 0,
            "garble_metrics": metrics,
            "reject_reason": reject_reason,
        }

        if reject_reason:
            rejected_rows.append(payload)
        else:
            total_tokens += int(payload["token_estimate"])
            base_rows.append(payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = output_dir / "base_dataset.jsonl"
    rejected_path = output_dir / "rejected_dataset.jsonl"
    report_path = output_dir / "dataset_audit_report.json"
    cost_path = output_dir / "cost_estimate.md"
    write_jsonl(base_path, base_rows)
    write_jsonl(rejected_path, rejected_rows)

    reason_counts: dict[str, int] = {}
    for row in rejected_rows:
        reason = str(row.get("reject_reason", "") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    cost = estimate_embedding_cost(
        total_tokens=total_tokens,
        cny_per_million_tokens=cny_per_million_tokens,
        budget_cny=budget_cny,
    )
    report = {
        "manifest_path": str(manifest_path) if manifest_path is not None else "",
        "input_root": str(input_root) if input_root is not None else "",
        "total_rows": len(rows),
        "base_rows": len(base_rows),
        "rejected_rows": len(rejected_rows),
        "rejected_reason_counts": reason_counts,
        "output": {
            "base_dataset": str(base_path),
            "rejected_dataset": str(rejected_path),
            "normalized_html_dir": str(normalized_dir),
            "cost_estimate_md": str(cost_path),
        },
        "embedding_cost": cost,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cost_path.write_text(_render_cost_estimate_md(cost), encoding="utf-8")
    return report


def audit_manifest(manifest_path: Path | None, input_root: Path | None = None, output_json: Path | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if manifest_path is not None:
        rows.extend(iter_jsonl(manifest_path))
    if input_root is not None:
        rows.extend(collect_input_rows(input_root))
    has_inline_html = 0
    by_ext: dict[str, int] = {}
    for row in rows:
        if str(row.get("html", "") or "").strip():
            has_inline_html += 1
        src = resolve_source_path(row)
        ext = src.suffix.lower() if src else ""
        by_ext[ext] = by_ext.get(ext, 0) + 1
    payload = {
        "manifest_path": str(manifest_path) if manifest_path is not None else "",
        "input_root": str(input_root) if input_root is not None else "",
        "total_rows": len(rows),
        "rows_with_inline_html": has_inline_html,
        "source_extension_counts": by_ext,
    }
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def check_mysql_fulltext(
    user: str,
    password: str,
    host: str = "127.0.0.1",
    port: int = 3306,
    mysql_bin: str = "mysql",
) -> dict[str, Any]:
    columns_query = """
SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,DATA_TYPE
FROM information_schema.columns
WHERE TABLE_SCHEMA NOT IN ('mysql','performance_schema','information_schema','sys')
  AND (
    LOWER(COLUMN_NAME) LIKE '%text%' OR
    LOWER(COLUMN_NAME) LIKE '%html%' OR
    LOWER(COLUMN_NAME) LIKE '%content%' OR
    LOWER(COLUMN_NAME) LIKE '%full%' OR
    LOWER(DATA_TYPE) IN ('text','mediumtext','longtext')
  )
ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION;
""".strip()
    candidates = _mysql_query(mysql_bin, user, password, host, port, columns_query)
    out_rows: list[dict[str, Any]] = []
    for c in candidates:
        schema = c.get("TABLE_SCHEMA", "")
        table = c.get("TABLE_NAME", "")
        column = c.get("COLUMN_NAME", "")
        total, non_empty, avg_len = _mysql_column_stats(mysql_bin, user, password, host, port, schema, table, column)
        pk_column = _mysql_primary_key(mysql_bin, user, password, host, port, schema, table)
        samples = _mysql_samples(mysql_bin, user, password, host, port, schema, table, column, pk_column)
        out_rows.append(
            {
                "schema": schema,
                "table": table,
                "column": column,
                "data_type": c.get("DATA_TYPE", ""),
                "total_rows": total,
                "non_empty_rows": non_empty,
                "avg_char_length": avg_len,
                "primary_key": pk_column,
                "samples": samples,
            }
        )
    return {"engine": "mysql", "candidate_columns": out_rows}


def _mysql_query(
    mysql_bin: str,
    user: str,
    password: str,
    host: str,
    port: int,
    query: str,
) -> list[dict[str, str]]:
    cmd = [
        mysql_bin,
        f"--host={host}",
        f"--port={int(port)}",
        f"--user={user}",
        f"--password={password}",
        "--batch",
        "--raw",
        "-e",
        query,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "mysql query failed")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    out: list[dict[str, str]] = []
    for line in lines[1:]:
        vals = line.split("\t")
        row = {header[i]: (vals[i] if i < len(vals) else "") for i in range(len(header))}
        out.append(row)
    return out


def _mysql_column_stats(
    mysql_bin: str,
    user: str,
    password: str,
    host: str,
    port: int,
    schema: str,
    table: str,
    column: str,
) -> tuple[int, int, float]:
    q = f"""
SELECT
  COUNT(*) AS total_rows,
  SUM(CASE WHEN COALESCE(CHAR_LENGTH(`{column}`),0) > 0 THEN 1 ELSE 0 END) AS non_empty_rows,
  AVG(NULLIF(CHAR_LENGTH(`{column}`),0)) AS avg_char_length
FROM `{schema}`.`{table}`;
""".strip()
    rows = _mysql_query(mysql_bin, user, password, host, port, q)
    if not rows:
        return 0, 0, 0.0
    row = rows[0]
    total = int(_safe_float(row.get("total_rows", "0"), 0.0))
    non_empty = int(_safe_float(row.get("non_empty_rows", "0"), 0.0))
    avg_len = _safe_float(row.get("avg_char_length", "0"), 0.0)
    return total, non_empty, avg_len


def _mysql_primary_key(
    mysql_bin: str,
    user: str,
    password: str,
    host: str,
    port: int,
    schema: str,
    table: str,
) -> str:
    q = f"""
SELECT COLUMN_NAME
FROM information_schema.statistics
WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME='{table}' AND INDEX_NAME='PRIMARY'
ORDER BY SEQ_IN_INDEX
LIMIT 1;
""".strip()
    rows = _mysql_query(mysql_bin, user, password, host, port, q)
    if not rows:
        return ""
    return str(rows[0].get("COLUMN_NAME", "") or "")


def _mysql_samples(
    mysql_bin: str,
    user: str,
    password: str,
    host: str,
    port: int,
    schema: str,
    table: str,
    column: str,
    pk_column: str,
) -> list[dict[str, Any]]:
    key = f"`{pk_column}`" if pk_column else "NULL"
    q = f"""
SELECT {key} AS sample_id, LEFT(`{column}`, 200) AS sample_text
FROM `{schema}`.`{table}`
WHERE COALESCE(CHAR_LENGTH(`{column}`),0) > 0
LIMIT 3;
""".strip()
    rows = _mysql_query(mysql_bin, user, password, host, port, q)
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({"sample_id": row.get("sample_id", ""), "sample_text": row.get("sample_text", "")})
    return out


def _render_cost_estimate_md(cost: dict[str, Any]) -> str:
    lines = [
        "# Embedding Cost Estimate",
        "",
        f"- total_tokens: {cost.get('total_tokens', 0)}",
        f"- cny_per_million_tokens: {cost.get('cny_per_million_tokens', 0.0)}",
        f"- estimated_cost_cny: {cost.get('estimated_cost_cny', 0.0)}",
        f"- budget_cny: {cost.get('budget_cny', 0.0)}",
        f"- within_budget: {cost.get('within_budget', False)}",
        "",
    ]
    return "\n".join(lines)


def _normalize_reject_reason(detail: str) -> str:
    text = str(detail or "").strip().lower()
    if "source_too_large" in text:
        return "source_too_large"
    if "mineru_cloud" in text or "mineru" in text:
        return "pdf_mineru_failed"
    if "missing_source_path" in text:
        return "missing_source_path"
    if "source_not_found" in text:
        return "source_not_found"
    return "normalize_error"


def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Literature dataset and DB fulltext tooling.")
    sub = p.add_subparsers(dest="command", required=True)

    ap_audit = sub.add_parser("dataset-audit")
    ap_audit.add_argument("--manifest-path", type=Path, default=None)
    ap_audit.add_argument("--input-root", type=Path, default=None)
    ap_audit.add_argument("--output-json", type=Path, required=True)

    ap_base = sub.add_parser("dataset-build-base")
    ap_base.add_argument("--manifest-path", type=Path, default=None)
    ap_base.add_argument("--input-root", type=Path, default=None)
    ap_base.add_argument("--output-dir", type=Path, required=True)
    ap_base.add_argument("--garble-threshold", type=float, default=0.02)
    ap_base.add_argument("--cny-per-million-tokens", type=float, default=2.0)
    ap_base.add_argument("--budget-cny", type=float, default=100.0)
    ap_base.add_argument("--max-source-bytes", type=int, default=8_000_000)

    ap_mysql = sub.add_parser("db-check-mysql")
    ap_mysql.add_argument("--output-json", type=Path, required=True)
    ap_mysql.add_argument("--mysql-bin", default="mysql")
    ap_mysql.add_argument("--host", default="127.0.0.1")
    ap_mysql.add_argument("--port", type=int, default=3306)
    ap_mysql.add_argument("--user", required=True)
    ap_mysql.add_argument("--password", required=True)

    return p


def main() -> None:
    args = build_cli().parse_args()
    if args.command == "dataset-audit":
        payload = audit_manifest(args.manifest_path, input_root=args.input_root, output_json=args.output_json)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if args.command == "dataset-build-base":
        payload = build_base_dataset(
            manifest_path=args.manifest_path,
            output_dir=args.output_dir,
            input_root=args.input_root,
            garble_threshold=args.garble_threshold,
            cny_per_million_tokens=args.cny_per_million_tokens,
            budget_cny=args.budget_cny,
            max_source_bytes=args.max_source_bytes,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if args.command == "db-check-mysql":
        payload = check_mysql_fulltext(
            user=args.user,
            password=args.password,
            host=args.host,
            port=args.port,
            mysql_bin=args.mysql_bin,
        )
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
