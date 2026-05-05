from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


def _read_json_line() -> dict[str, Any] | None:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    text = line.decode("utf-8", errors="ignore").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _api_get_json(base_url: str, path: str) -> dict[str, Any]:
    req = Request(f"{base_url.rstrip('/')}{path}", method="GET")
    with urlopen(req, timeout=45) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}


def _build_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "rag_search",
            "description": "Search paragraph-level evidence in literature library.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 12},
                    "library_id": {"type": "string"},
                },
                "required": ["query", "library_id"],
            },
        },
        {
            "name": "graph_search",
            "description": "Search graph cards by query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "library_id": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "weaviate_query",
            "description": "Query Weaviate-backed literature retrieval endpoint.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "library_id": {"type": "string"},
                },
                "required": ["query", "library_id"],
            },
        },
        {
            "name": "weaviate_fetch_object",
            "description": "Fetch paper/object detail by paper_id or doi.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "paper_id_or_doi": {"type": "string"},
                },
                "required": ["paper_id_or_doi"],
            },
        },
    ]


def _tool_result_text(obj: dict[str, Any], cap: int = 1800) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    return text[:cap]


def _handle_rag_search(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    library_id = str(arguments.get("library_id", "") or os.getenv("KN_DEFAULT_LIBRARY_ID", "") or "").strip()
    top_k = max(1, min(12, int(arguments.get("top_k", 8) or 8)))
    if not query:
        raise RuntimeError("query_required")
    if not library_id:
        raise RuntimeError("library_id_required")
    payload = _api_get_json(
        base_url,
        f"/literature/search?query={quote(query)}&top_k={top_k}&levels=paragraph&include_expanded_context=true&library_id={quote(library_id)}",
    )
    merged = payload.get("merged_hits", []) if isinstance(payload, dict) else []
    hits = merged if isinstance(merged, list) else []
    paragraph_hits: list[dict[str, Any]] = []
    for item in hits:
        if not isinstance(item, dict):
            continue
        ctx = item.get("context") if isinstance(item.get("context"), dict) else {}
        paragraph = ctx.get("paragraph") if isinstance(ctx.get("paragraph"), dict) else {}
        document = ctx.get("document") if isinstance(ctx.get("document"), dict) else {}
        metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        text = str(paragraph.get("text", "") or item.get("text", "") or "").strip()
        if not text:
            continue
        source_html = str(paragraph.get("source_html", "") or document.get("source_html", "") or "").strip()
        paper_key = str(metadata.get("paper_key", "") or "").strip()
        if (not paper_key) and source_html:
            normalized = source_html.replace("\\", "/")
            marker = "/corpus/papers/"
            idx = normalized.lower().find(marker)
            if idx >= 0:
                rest = normalized[idx + len(marker) :]
                paper_key = rest.split("/", 1)[0].strip()
        paragraph_hits.append(
            {
                "id": str(item.get("id", "") or item.get("paper_id", "") or ""),
                "title": str(item.get("title", "") or item.get("paper_id", "") or ""),
                "text": text,
                "paper_id": str(item.get("paper_id", "") or ""),
                "paper_key": paper_key,
                "html_path": source_html,
            }
        )
    return {
        "query": query,
        "library_id": library_id,
        "paragraph_hits": paragraph_hits[:top_k],
        "paragraph_count": len(paragraph_hits),
    }


def _handle_graph_search(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    limit = max(1, min(20, int(arguments.get("limit", 8) or 8)))
    if not query:
        raise RuntimeError("query_required")
    payload = _api_get_json(base_url, f"/graph/search?query={quote(query)}&limit={limit}")
    results = payload.get("results", []) if isinstance(payload, dict) else []
    return {
        "query": query,
        "results": results if isinstance(results, list) else [],
    }


def _handle_weaviate_query(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    library_id = str(arguments.get("library_id", "") or os.getenv("KN_DEFAULT_LIBRARY_ID", "") or "").strip()
    top_k = max(1, min(50, int(arguments.get("top_k", 10) or 10)))
    if not query:
        raise RuntimeError("query_required")
    if not library_id:
        raise RuntimeError("library_id_required")
    payload = _api_get_json(
        base_url,
        f"/literature/search?query={quote(query)}&top_k={top_k}&include_expanded_context=true&library_id={quote(library_id)}",
    )
    return {
        "query": query,
        "library_id": library_id,
        "keyword_hits": payload.get("keyword_hits", []),
        "rag_hits": payload.get("rag_hits", []),
        "merged_hits": payload.get("merged_hits", []),
    }


def _handle_weaviate_fetch_object(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    key = str(arguments.get("paper_id_or_doi", "") or "").strip()
    if not key:
        raise RuntimeError("paper_id_or_doi_required")
    payload = _api_get_json(base_url, f"/paper/{quote(key)}")
    return payload


def _call_tool(base_url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "rag_search":
        return _handle_rag_search(base_url, arguments)
    if name == "graph_search":
        return _handle_graph_search(base_url, arguments)
    if name == "weaviate_query":
        return _handle_weaviate_query(base_url, arguments)
    if name == "weaviate_fetch_object":
        return _handle_weaviate_fetch_object(base_url, arguments)
    raise RuntimeError(f"tool_not_found:{name}")


def main() -> None:
    from kn_graph.config import Settings
    boot = Settings()
    boot.load_global_settings()
    default_url = f"http://{boot.host}:{boot.port}"
    parser = argparse.ArgumentParser(description="KN Graph MCP server")
    parser.add_argument("--api-base-url", default=default_url)
    args = parser.parse_args()
    base_url = str(args.api_base_url or "").strip() or "http://127.0.0.1:8013"
    tools = _build_tools()

    while True:
        msg = _read_json_line()
        if msg is None:
            break
        if not isinstance(msg, dict):
            continue
        req_id = msg.get("id")
        method = str(msg.get("method", "") or "")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "kn_graph_tools", "version": "0.1.0"},
                        "capabilities": {"tools": {}},
                    },
                }
            )
            continue

        if method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": tools,
                    },
                }
            )
            continue

        if method == "tools/call":
            name = str(params.get("name", "") or "").strip()
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                result = _call_tool(base_url, name, arguments)
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": _tool_result_text(result)}],
                            "structuredContent": result,
                            "isError": False,
                        },
                    }
                )
            except Exception as exc:
                err = str(exc)
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": err}],
                            "structuredContent": {"error": err},
                            "isError": True,
                        },
                    }
                )
            continue

        if req_id is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"method_not_found:{method}"},
                }
            )


if __name__ == "__main__":
    main()
