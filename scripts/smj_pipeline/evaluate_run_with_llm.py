from __future__ import annotations

import argparse
import json
import importlib.util
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompt"
_JUDGE_PROMPT_PATH = _PROMPT_ROOT / "judge_system_prompt.md"


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_evaluate", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()

def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _clean_html_and_text(raw_html: str) -> tuple[str, str, str]:
    soup = BeautifulSoup(raw_html, "html.parser")
    for bad in soup.select("script,style,noscript"):
        bad.decompose()
    marker = ""
    for h in soup.find_all(re.compile("^h[1-6]$")):
        txt = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip()
        low = txt.lower()
        if low in {"references", "reference", "bibliography", "citing literature", "cited by"} or txt == "参考文献":
            marker = txt
            node = h
            while node.parent is not None:
                nxt = [x for x in node.next_siblings]
                if nxt:
                    for x in nxt:
                        if hasattr(x, "extract"):
                            x.extract()
                    node.extract()
                    break
                node = node.parent
            break
    clean_html = str(soup)
    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return clean_html, text, marker


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[TRUNCATED at {limit}]"


def _parse_gt_markdown(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    sec_pat = re.compile(r"^##\s+(.+?)\s*$", re.M)
    matches = list(sec_pat.finditer(text))
    out: dict[str, dict[str, Any]] = {}
    for i, m in enumerate(matches):
        key = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        fm = re.search(r"```[a-zA-Z]*\n(.*?)```", block, re.S)
        if not fm:
            continue
        try:
            obj = yaml.safe_load(fm.group(1))
        except Exception:
            continue
        if isinstance(obj, dict):
            out[key] = obj
    return out


def _call_glm(api_key: str, model: str, system_prompt: str, user_content: str, base_url: str) -> str:
    url = base_url
    # NVIDIA endpoint can be very slow, especially with long source text/html in user_content.
    # This call keeps retry/backoff to tolerate provider-side queueing and transient timeouts.
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    for i in range(6):
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and i < 5:
                time.sleep(4 * (i + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        except Exception:
            if i < 5:
                time.sleep(3 * (i + 1))
                continue
            raise
    raise RuntimeError("judge call failed")


def _extract_json(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    s = t.find("{")
    e = t.rfind("}")
    if s >= 0 and e > s:
        t = t[s : e + 1]
    obj = json.loads(t)
    if not isinstance(obj, dict):
        raise ValueError("judge output is not a JSON object")
    return obj


def _judge_prompt() -> str:
    return _JUDGE_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(text or "").strip())


def _normalize_verdict(raw_verdict: Any, score: int) -> str:
    t = str(raw_verdict or "").strip().lower()
    if t in {"accurate", "partially_accurate", "inaccurate"}:
        return t
    if "inconsistent" in t or "not consistent" in t:
        return "inaccurate"
    if "partial" in t:
        return "partially_accurate"
    if "accurate" in t or "consistent" in t or "high consistency" in t:
        if score >= 85:
            return "accurate"
        return "partially_accurate"
    if score >= 85:
        return "accurate"
    if score >= 60:
        return "partially_accurate"
    return "inaccurate"


def main() -> None:
    _ENV_UTILS.load_repo_env()
    ap = argparse.ArgumentParser(description="Evaluate one extracted run with LLM (GT mode or consistency mode).")
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--raw-output-jsonl", type=Path, default=None)
    ap.add_argument("--gt-markdown", type=Path, default=None)
    ap.add_argument("--provider", choices=["zhipu", "nvidia"], default="zhipu")
    ap.add_argument("--model", default="glm-4-plus")
    ap.add_argument("--api-key-env", default="ZHIPU_API_KEY")
    ap.add_argument("--base-url", default="https://open.bigmodel.cn/api/paas/v4/chat/completions")
    ap.add_argument("--max-html-chars", type=int, default=90000)
    ap.add_argument("--max-text-chars", type=int, default=120000)
    ap.add_argument("--reference-mode", choices=["text", "html+text"], default="text")
    args = ap.parse_args()

    provider = str(args.provider).strip().lower()
    env_name = str(args.api_key_env).strip()
    model = str(args.model).strip()
    base_url = str(args.base_url).strip()
    if provider == "nvidia":
        if env_name == "ZHIPU_API_KEY":
            env_name = "NVIDIA_API_KEY"
        if model == "glm-4-plus":
            model = "z-ai/glm4.7"
        if base_url == "https://open.bigmodel.cn/api/paas/v4/chat/completions":
            base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        # Reminder: evaluation payload contains long paper context; NVIDIA latency may be high.
        # For large runs, expect slower end-to-end evaluation time than Zhipu.

    key = os.getenv(env_name, "").strip()
    if not key:
        raise RuntimeError(f"missing api key env: {env_name}")

    run_dir = args.run_dir
    manifest = run_dir / "manifest_input.jsonl"
    raw_out = args.raw_output_jsonl or (run_dir / "raw_llm_outputs_from_batch.jsonl")
    if not manifest.exists() or not raw_out.exists():
        raise RuntimeError("run dir missing manifest_input.jsonl or raw_llm_outputs_from_batch.jsonl")

    gt_map: dict[str, dict[str, Any]] = {}
    if args.gt_markdown:
        gt_map = _parse_gt_markdown(args.gt_markdown)

    manifest_rows = _iter_jsonl(manifest)
    by_doi: dict[str, dict[str, Any]] = {}
    for r in manifest_rows:
        doi = str(r.get("doi", "")).strip()
        if doi:
            by_doi[doi] = r

    raw_rows = _iter_jsonl(raw_out)
    ok_rows = [r for r in raw_rows if str(r.get("status", "")).strip() in {"ok", "ok_raw"}]

    out_dir = run_dir / "evaluation_llm" / datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = out_dir / "raw"
    clean_dir = out_dir / "clean_html_no_refs"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)

    jsonl_out = out_dir / "judge_per_paper.jsonl"
    summary_out = out_dir / "judge_summary.md"

    stats = {"accurate": 0, "partially_accurate": 0, "inaccurate": 0, "failed": 0}

    with jsonl_out.open("w", encoding="utf-8", newline="\n") as fw:
        for row in ok_rows:
            doi = str(row.get("doi", "")).strip()
            pred_raw = str(row.get("raw_response", "")).strip()
            m = by_doi.get(doi, {})
            html_path = Path(str(m.get("offline_html_path", "")).strip()) if m else Path("")
            if not html_path.is_absolute():
                html_path = Path.cwd() / html_path

            try:
                raw_html = html_path.read_text(encoding="utf-8", errors="ignore")
                clean_html, clean_text, marker = _clean_html_and_text(raw_html)
                offline_name = html_path.name.replace("_full.html", "_offline.html")
                gt_obj = gt_map.get(offline_name) if gt_map else None
                has_gt = isinstance(gt_obj, dict)
                payload = {
                    "doi": doi,
                    "offline_file": offline_name,
                    "ground_truth": gt_obj if has_gt else None,
                    "prediction_raw": pred_raw,
                    "reference_text_no_refs": _truncate(clean_text, args.max_text_chars),
                    "reference_marker": marker,
                }
                if args.reference_mode == "html+text":
                    payload["reference_html_no_refs"] = _truncate(clean_html, args.max_html_chars)
                raw_judge = _call_glm(key, model, _judge_prompt(), json.dumps(payload, ensure_ascii=False), base_url)
                parsed = _extract_json(raw_judge)
                score = parsed.get("consistency_score", 0)
                try:
                    score = int(float(score))
                except Exception:
                    score = 0
                score = max(0, min(100, score))
                verdict = _normalize_verdict(parsed.get("overall_verdict"), score)
                stats[verdict] += 1

                safe = _safe_name(doi)
                raw_file = raw_dir / f"{safe}.raw.md"
                raw_file.write_text(raw_judge, encoding="utf-8")
                clean_file = clean_dir / f"{safe}.html"
                clean_file.write_text(clean_html, encoding="utf-8")

                fw.write(
                    json.dumps(
                        {
                            "doi": doi,
                            "offline_file": offline_name,
                            "ok": True,
                            "mode": "gt+prediction" if has_gt else "prediction+source_consistency",
                            "verdict": verdict,
                            "score": score,
                            "judge": parsed,
                            "raw_file": str(raw_file),
                            "clean_html_file": str(clean_file),
                            "reference_marker": marker,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                print(f"[OK] {doi}: {verdict} ({score})")
            except Exception as e:  # noqa: BLE001
                stats["failed"] += 1
                fw.write(json.dumps({"doi": doi, "ok": False, "error": str(e)}, ensure_ascii=False) + "\n")
                print(f"[FAILED] {doi}: {e}")

    total = sum(stats.values())
    lines = [
        "# Run LLM 评测报告",
        "",
        f"- run_dir: `{run_dir}`",
        f"- total: {total}",
        f"- accurate: {stats['accurate']}",
        f"- partially_accurate: {stats['partially_accurate']}",
        f"- inaccurate: {stats['inaccurate']}",
        f"- failed: {stats['failed']}",
        f"- jsonl: `{jsonl_out}`",
    ]
    summary_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"out_dir": str(out_dir), "jsonl": str(jsonl_out), "summary": str(summary_out), "stats": stats},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

