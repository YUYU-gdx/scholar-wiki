from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from kn_graph._compat import bundle_root


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _write(proc: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    assert proc.stdin is not None
    proc.stdin.write(data)
    proc.stdin.flush()


def _read_until_id(proc: subprocess.Popen[bytes], req_id: int, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    assert proc.stdout is not None
    while time.time() < deadline:
        raw = proc.stdout.readline()
        if not raw:
            continue
        line = _decode(raw).strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue
        if int(msg.get("id", -1) or -1) == int(req_id):
            return msg
    raise TimeoutError(f"mcp_probe_timeout:req_id={req_id}")


def _request(proc: subprocess.Popen[bytes], req_id: int, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    _write(proc, payload)
    msg = _read_until_id(proc, req_id=req_id, timeout_seconds=25.0)
    if isinstance(msg.get("error"), dict):
        raise RuntimeError(f"mcp_probe_request_failed:{method}:{msg['error']}")
    result = msg.get("result")
    return result if isinstance(result, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe KN MCP server connectivity and rag_search tool.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8013", help="Backend API base URL")
    parser.add_argument("--library-id", required=True, help="Target library id")
    parser.add_argument("--query", default="supply chain resilience", help="rag_search query")
    parser.add_argument("--top-k", type=int, default=3, help="rag_search top_k")
    args = parser.parse_args()

    mcp_server_path = (
        bundle_root()
        / "scripts"
        / "smj_pipeline"
        / "kn_mcp_server.py"
    )
    cmd = [sys.executable, str(mcp_server_path), "--api-base-url", str(args.api_base_url)]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )

    try:
        init_res = _request(
            proc,
            req_id=1,
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "mcp_probe", "version": "0.1.0"},
                "capabilities": {},
            },
        )
        print("[initialize]", json.dumps(init_res, ensure_ascii=False))

        tools_res = _request(proc, req_id=2, method="tools/list", params={})
        tools = tools_res.get("tools") if isinstance(tools_res.get("tools"), list) else []
        print("[tools]", json.dumps([str(x.get("name", "")) for x in tools if isinstance(x, dict)], ensure_ascii=False))

        rag_res = _request(
            proc,
            req_id=3,
            method="tools/call",
            params={
                "name": "rag_search",
                "arguments": {
                    "query": str(args.query or "").strip(),
                    "top_k": max(1, int(args.top_k or 3)),
                    "library_id": str(args.library_id or "").strip(),
                },
            },
        )
        structured = rag_res.get("structuredContent") if isinstance(rag_res.get("structuredContent"), dict) else {}
        paragraph_hits = structured.get("paragraph_hits") if isinstance(structured.get("paragraph_hits"), list) else []
        print("[rag_search]", json.dumps({"paragraph_count": len(paragraph_hits), "library_id": structured.get("library_id", "")}, ensure_ascii=False))
        if paragraph_hits:
            first = paragraph_hits[0] if isinstance(paragraph_hits[0], dict) else {}
            print("[rag_search:first]", json.dumps({"id": first.get("id", ""), "title": first.get("title", "")}, ensure_ascii=False))
        return 0
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
