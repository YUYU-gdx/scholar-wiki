from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

import requests


def _load_module(relative_path: str, module_name: str):
    module_path = Path(__file__).resolve().parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_ENV_MOD = _load_module("env_utils.py", "smj_pipeline_env_utils_for_one_md")
_LITERATURE_MOD = _load_module("literature/service.py", "smj_pipeline_literature_service_for_one_md")
load_repo_env = _ENV_MOD.load_repo_env
LiteratureService = _LITERATURE_MOD.LiteratureService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import one MD file into Weaviate with Zhipu embedding.")
    parser.add_argument("--weaviate-url", default="http://127.0.0.1:8090")
    parser.add_argument("--md-path", type=Path, default=None)
    parser.add_argument(
        "--md-root",
        type=Path,
        default=Path("outputs/mineru_recovery_full_from_outputs_20260419_120258/downloads/final_named"),
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=Path("outputs/literature_base/manifest_one.jsonl"),
    )
    parser.add_argument("--health-only", action="store_true")
    return parser.parse_args()


def _configure_no_proxy() -> None:
    no_proxy_values = ["127.0.0.1", "localhost"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.getenv(key, "")
        parts = [p.strip() for p in existing.split(",") if p.strip()]
        for v in no_proxy_values:
            if v not in parts:
                parts.append(v)
        os.environ[key] = ",".join(parts)


def _weaviate_health_check(base_url: str) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = False
    endpoint = f"{base_url.rstrip('/')}/v1/.well-known/ready"
    resp = session.get(endpoint, timeout=8)
    return {
        "endpoint": endpoint,
        "status_code": int(resp.status_code),
        "ok": int(resp.status_code) == 200,
        "body_preview": (resp.text or "")[:200],
    }


def _pick_md_file(md_path: Path | None, md_root: Path) -> Path:
    if md_path is not None:
        if not md_path.exists():
            raise RuntimeError(f"md_not_found:{md_path}")
        return md_path
    candidates = sorted(md_root.glob("*.md"))
    if not candidates:
        raise RuntimeError(f"no_md_found_under:{md_root}")
    return candidates[0]


def _write_single_manifest(md_path: Path, manifest_path: Path) -> dict[str, Any]:
    paper_id = md_path.stem
    payload = {
        "paper_id": paper_id,
        "doi": f"md::{paper_id}",
        "title": paper_id,
        "source_path": str(md_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def _verify_inserted(service: Any, paper_id: str) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for class_name in ("LiteratureSentence", "LiteratureParagraph", "LiteratureDocument"):
        resp = service.weaviate._request("GET", f"/v1/objects?class={class_name}&limit=200")
        objs = resp.get("objects", []) if isinstance(resp, dict) else []
        hit = None
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            props = obj.get("properties", {}) if isinstance(obj.get("properties"), dict) else {}
            if str(props.get("paper_id", "")) == paper_id:
                hit = {
                    "id": str(obj.get("id", "")),
                    "paper_id": str(props.get("paper_id", "")),
                    "source_html": str(props.get("source_html", "")),
                    "text_preview": str(props.get("text", "") or props.get("full_text", ""))[:120],
                }
                break
        checks[class_name] = {
            "found": hit is not None,
            "sample": hit,
        }
    return checks


def main() -> None:
    load_repo_env()
    args = parse_args()
    _configure_no_proxy()
    os.environ["WEAVIATE_URL"] = str(args.weaviate_url).strip()
    os.environ.setdefault("LITERATURE_EMBEDDING_MODEL", "embedding-3")

    health = _weaviate_health_check(str(args.weaviate_url))
    if not health["ok"]:
        raise RuntimeError(f"weaviate_not_ready:{json.dumps(health, ensure_ascii=False)}")
    if args.health_only:
        print(json.dumps({"health": health}, ensure_ascii=False, indent=2))
        return

    md_path = _pick_md_file(args.md_path, args.md_root)
    manifest_row = _write_single_manifest(md_path=md_path, manifest_path=args.manifest_path)
    service = LiteratureService()
    import_result = service.import_manifest(args.manifest_path)
    if int(import_result.get("imported_count", 0)) != 1:
        raise RuntimeError(f"unexpected_imported_count:{import_result}")
    if int(import_result.get("sentence_count", 0)) <= 0:
        raise RuntimeError(f"unexpected_sentence_count:{import_result}")
    if int(import_result.get("paragraph_count", 0)) <= 0:
        raise RuntimeError(f"unexpected_paragraph_count:{import_result}")
    if int(import_result.get("document_count", 0)) != 1:
        raise RuntimeError(f"unexpected_document_count:{import_result}")

    checks = _verify_inserted(service, paper_id=str(manifest_row["paper_id"]))
    payload = {
        "health": health,
        "manifest_path": str(args.manifest_path),
        "manifest_row": manifest_row,
        "import_result": import_result,
        "weaviate_checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise
