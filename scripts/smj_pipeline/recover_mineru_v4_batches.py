from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

import requests

from mineru_agent_common import safe_id, write_json, write_json_atomic, write_jsonl


UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
DEFAULT_TEXT_SUFFIXES = {
    ".txt",
    ".log",
    ".json",
    ".jsonl",
    ".md",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".py",
    ".ps1",
    ".cmd",
    ".bat",
    ".sh",
    ".ini",
    ".toml",
    ".xml",
    ".html",
}


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_recover_mineru_v4", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Recover MinerU v4 batch outputs from local traces and API lookup.")
    ap.add_argument("--manifest", type=Path, required=True, help="Manifest JSONL used as completeness baseline.")
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--search-roots", nargs="*", default=None, help="Roots to scan for candidate batch UUIDs.")
    ap.add_argument("--include-recycle-bin", action="store_true", help="Include recycle bin path in discovery scan.")
    ap.add_argument("--mineru-api-key-env", default="MINERU_API_KEY")
    ap.add_argument("--base-url", default="https://mineru.net/api/v4")
    ap.add_argument("--max-file-bytes", type=int, default=2_000_000)
    ap.add_argument("--max-files", type=int, default=60_000)
    ap.add_argument("--api-timeout-seconds", type=int, default=60)
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--retry-delays", default="3,10,25")
    ap.add_argument("--seed-batch-ids", nargs="*", default=None, help="Extra candidate batch IDs to include.")
    ap.add_argument("--seed", type=int, default=42)
    return ap.parse_args()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def _parse_retry_delays(text: str) -> list[float]:
    out: list[float] = []
    for part in str(text).split(","):
        t = part.strip()
        if not t:
            continue
        try:
            out.append(float(t))
        except ValueError:
            continue
    return out or [3.0, 10.0, 25.0]


def _sleep_jitter(seconds: float) -> None:
    delta = random.uniform(-0.2, 0.2) * max(1.0, seconds)
    time.sleep(max(0.0, seconds + delta))


def _default_run_dir() -> Path:
    return Path("outputs") / f"mineru_recovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _default_search_roots(include_recycle_bin: bool) -> list[Path]:
    roots: list[Path] = [Path.cwd()]
    hist = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt"
    if hist.exists():
        roots.append(hist)
    if include_recycle_bin:
        recycle = Path("C:/$Recycle.Bin")
        if recycle.exists():
            roots.append(recycle)
    return roots


def _iter_candidate_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    if not root.exists():
        return files
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() and p.suffix.lower() not in DEFAULT_TEXT_SUFFIXES:
            continue
        files.append(p)
    return files


def _extract_candidates_from_text(path: Path, max_file_bytes: int) -> set[str]:
    try:
        if path.stat().st_size > max_file_bytes:
            return set()
    except Exception:
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()
    return {m.group(0).lower() for m in UUID_RE.finditer(text)}


def _load_manifest_dois(path: Path) -> list[str]:
    out: list[str] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            row = json.loads(t)
            if not isinstance(row, dict):
                continue
            doi = str(row.get("doi", "")).strip().lower()
            if doi:
                out.append(doi)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _guess_doi_from_filename(file_name: str, manifest_dois: list[str]) -> str:
    name_key = _norm(Path(file_name).stem)
    if not name_key:
        return ""
    best = ""
    best_score = -1
    for doi in manifest_dois:
        dk = _norm(doi)
        if not dk:
            continue
        score = 0
        if dk in name_key:
            score = len(dk)
        elif name_key in dk:
            score = len(name_key)
        elif "1002" in dk and "1002" in name_key:
            overlap = len(set(re.findall(r"[a-z0-9]{3,}", dk)).intersection(set(re.findall(r"[a-z0-9]{3,}", name_key))))
            score = overlap
        if score > best_score:
            best_score = score
            best = doi
    if best_score <= 0:
        return ""
    return best


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"candidates": {}, "updated_at": _now_iso()}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"candidates": {}, "updated_at": _now_iso()}
    if not isinstance(obj, dict):
        return {"candidates": {}, "updated_at": _now_iso()}
    if not isinstance(obj.get("candidates"), dict):
        obj["candidates"] = {}
    return obj


def _query_batch(
    batch_id: str,
    args: argparse.Namespace,
    headers: dict[str, str],
    retry_delays: list[float],
) -> dict[str, Any]:
    url = f"{str(args.base_url).rstrip('/')}/extract-results/batch/{batch_id}"
    attempts = max(1, int(args.max_retries))
    for attempt in range(1, attempts + 1):
        try:
            res = requests.get(url, headers=headers, timeout=int(args.api_timeout_seconds))
            raw = res.text
            try:
                obj = res.json()
            except Exception:
                obj = {"raw": raw[:5000]}
            if res.status_code != 200:
                if attempt < attempts:
                    delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                    _log(f"[query] batch={batch_id} http={res.status_code}, retry in {delay}s")
                    _sleep_jitter(delay)
                    continue
                return {"ok": False, "http": res.status_code, "error": f"http_{res.status_code}", "response": obj}
            if not isinstance(obj, dict) or int(obj.get("code", -1)) != 0:
                return {"ok": False, "http": res.status_code, "error": f"code_{obj.get('code')}", "response": obj}
            data = obj.get("data")
            if not isinstance(data, dict):
                return {"ok": False, "http": res.status_code, "error": "missing_data", "response": obj}
            extract_result = data.get("extract_result")
            if not isinstance(extract_result, list) or not extract_result:
                return {"ok": False, "http": res.status_code, "error": "empty_extract_result", "response": obj}
            row = extract_result[0] if isinstance(extract_result[0], dict) else {}
            return {
                "ok": True,
                "http": res.status_code,
                "response": obj,
                "state": str(row.get("state", "")).strip().lower(),
                "file_name": str(row.get("file_name", "")).strip(),
                "full_zip_url": str(row.get("full_zip_url", "")).strip(),
                "err_msg": str(row.get("err_msg", "")).strip(),
            }
        except Exception as exc:
            if attempt < attempts:
                delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                _log(f"[query] batch={batch_id} exception={type(exc).__name__}, retry in {delay}s")
                _sleep_jitter(delay)
                continue
            return {"ok": False, "http": 0, "error": f"exception:{type(exc).__name__}:{exc}", "response": {}}
    return {"ok": False, "http": 0, "error": "unknown", "response": {}}


def _download_zip(
    url: str,
    out_path: Path,
    args: argparse.Namespace,
    retry_delays: list[float],
) -> dict[str, Any]:
    attempts = max(1, int(args.max_retries))
    for attempt in range(1, attempts + 1):
        try:
            res = requests.get(url, timeout=max(120, int(args.api_timeout_seconds)))
            if res.status_code == 200:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(res.content)
                return {"ok": True, "http": 200, "size_bytes": len(res.content)}
            if attempt < attempts:
                delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                _log(f"[download] http={res.status_code}, retry in {delay}s")
                _sleep_jitter(delay)
                continue
            return {"ok": False, "http": res.status_code, "error": f"http_{res.status_code}"}
        except Exception as exc:
            if attempt < attempts:
                delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                _log(f"[download] exception={type(exc).__name__}, retry in {delay}s")
                _sleep_jitter(delay)
                continue
            return {"ok": False, "http": 0, "error": f"exception:{type(exc).__name__}:{exc}"}
    return {"ok": False, "http": 0, "error": "unknown"}


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    random.seed(int(args.seed))
    retry_delays = _parse_retry_delays(args.retry_delays)

    run_dir = args.run_dir if args.run_dir else _default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir = run_dir / "downloads" / "zips_raw"
    discovery_checkpoint_path = run_dir / "checkpoint_discovery.json"
    download_checkpoint_path = run_dir / "checkpoint_download.json"

    manifest_dois = _load_manifest_dois(args.manifest)
    _log(f"loaded manifest dois: {len(manifest_dois)}")

    roots: list[Path] = []
    if args.search_roots:
        roots = [Path(x) for x in args.search_roots]
    else:
        roots = _default_search_roots(args.include_recycle_bin)
    _log(f"scan roots: {[str(x) for x in roots]}")

    discovery_ckpt = _load_checkpoint(discovery_checkpoint_path)
    discovery_candidates: dict[str, Any] = discovery_ckpt.setdefault("candidates", {})
    discovered_sources: dict[str, set[str]] = defaultdict(set)

    scanned_files = 0
    for root in roots:
        files = _iter_candidate_files(root)
        for path in files:
            scanned_files += 1
            if scanned_files > int(args.max_files):
                _log(f"scan hit max_files={args.max_files}; stop further scanning")
                break
            ids = _extract_candidates_from_text(path, int(args.max_file_bytes))
            for bid in ids:
                discovered_sources[bid].add(str(path))
        if scanned_files > int(args.max_files):
            break

    for seed_id in (args.seed_batch_ids or []):
        text = str(seed_id).strip().lower()
        if UUID_RE.fullmatch(text):
            discovered_sources[text].add("seed")

    _log(f"candidate batch ids discovered: {len(discovered_sources)}")
    for bid, srcs in discovered_sources.items():
        entry = discovery_candidates.get(bid, {})
        if not isinstance(entry, dict):
            entry = {}
        old = set(entry.get("source_paths", [])) if isinstance(entry.get("source_paths"), list) else set()
        merged = sorted(old.union(srcs))
        entry["source_paths"] = merged
        entry.setdefault("status", "pending")
        entry["updated_at"] = _now_iso()
        discovery_candidates[bid] = entry
    discovery_ckpt["updated_at"] = _now_iso()
    write_json_atomic(discovery_checkpoint_path, discovery_ckpt)

    api_key = str(os.getenv(args.mineru_api_key_env, "")).strip()
    if not api_key:
        raise RuntimeError(f"missing env: {args.mineru_api_key_env}")
    headers = {"Authorization": f"Bearer {api_key}"}

    valid_rows: list[dict[str, Any]] = []
    to_check = [bid for bid, e in discovery_candidates.items() if str(e.get("status", "")).lower() not in ("valid", "invalid")]
    _log(f"batch ids to verify by api: {len(to_check)}")
    checked = 0
    for bid in to_check:
        checked += 1
        res = _query_batch(bid, args, headers, retry_delays)
        entry = discovery_candidates.get(bid, {})
        if res.get("ok"):
            file_name = str(res.get("file_name", "")).strip()
            doi_guess = _guess_doi_from_filename(file_name, manifest_dois)
            entry.update(
                {
                    "status": "valid",
                    "state": str(res.get("state", "")),
                    "file_name": file_name,
                    "full_zip_url": str(res.get("full_zip_url", "")),
                    "err_msg": str(res.get("err_msg", "")),
                    "doi_guess": doi_guess,
                    "checked_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            _log(f"[verify {checked}/{len(to_check)}] valid batch={bid} state={entry.get('state')} doi_guess={doi_guess}")
        else:
            entry.update(
                {
                    "status": "invalid",
                    "error": str(res.get("error", "")),
                    "checked_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            _log(f"[verify {checked}/{len(to_check)}] invalid batch={bid} error={entry.get('error')}")
        discovery_candidates[bid] = entry
        discovery_ckpt["updated_at"] = _now_iso()
        write_json_atomic(discovery_checkpoint_path, discovery_ckpt)

    for bid, e in discovery_candidates.items():
        if str(e.get("status", "")).lower() != "valid":
            continue
        valid_rows.append(
            {
                "batch_id": bid,
                "state": str(e.get("state", "")),
                "file_name": str(e.get("file_name", "")),
                "full_zip_url": str(e.get("full_zip_url", "")),
                "err_msg": str(e.get("err_msg", "")),
                "doi_guess": str(e.get("doi_guess", "")),
                "source_paths": e.get("source_paths", []),
            }
        )

    index_path = run_dir / "recovered_batch_index.jsonl"
    write_jsonl(index_path, valid_rows)

    download_ckpt = _load_checkpoint(download_checkpoint_path)
    download_items: dict[str, Any] = download_ckpt.setdefault("candidates", {})
    for row in valid_rows:
        bid = str(row["batch_id"])
        item = download_items.get(bid, {})
        if not isinstance(item, dict):
            item = {}
        if str(item.get("status", "")).lower() == "done":
            continue
        zip_url = str(row.get("full_zip_url", "")).strip()
        if not zip_url:
            item.update({"status": "failed", "error": "missing_full_zip_url", "updated_at": _now_iso()})
            download_items[bid] = item
            continue
        out_zip = downloads_dir / f"{safe_id(bid, 120)}.zip"
        res = _download_zip(zip_url, out_zip, args, retry_delays)
        if res.get("ok"):
            item.update(
                {
                    "status": "done",
                    "zip_path": str(out_zip),
                    "size_bytes": int(res.get("size_bytes", 0)),
                    "updated_at": _now_iso(),
                }
            )
            _log(f"[download] done batch={bid} -> {out_zip.name}")
        else:
            item.update(
                {
                    "status": "failed",
                    "error": str(res.get("error", "")),
                    "http": int(res.get("http", 0) or 0),
                    "updated_at": _now_iso(),
                }
            )
            _log(f"[download] failed batch={bid} error={item.get('error')}")
        download_items[bid] = item
        download_ckpt["updated_at"] = _now_iso()
        write_json_atomic(download_checkpoint_path, download_ckpt)

    valid_count = len(valid_rows)
    downloaded_count = sum(1 for v in download_items.values() if isinstance(v, dict) and str(v.get("status", "")).lower() == "done")
    summary = {
        "generated_at": _now_iso(),
        "run_dir": str(run_dir),
        "manifest_path": str(args.manifest),
        "manifest_doi_count": len(manifest_dois),
        "scanned_files": scanned_files,
        "discovered_candidate_count": len(discovery_candidates),
        "valid_batch_count": valid_count,
        "downloaded_zip_count": downloaded_count,
        "index_path": str(index_path),
        "checkpoint_discovery": str(discovery_checkpoint_path),
        "checkpoint_download": str(download_checkpoint_path),
    }
    write_json(run_dir / "recovery_discovery_summary.json", summary)
    _log("summary " + json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

