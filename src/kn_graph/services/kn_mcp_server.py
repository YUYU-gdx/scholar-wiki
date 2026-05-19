from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kn_graph.services.variable_concept_index import VariableConceptIndexService

MAX_RETURN_CHARS = 12000
MAX_TEXT_SENTENCE = 360
MAX_TEXT_PARAGRAPH = 1600


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


def _api_post_json(base_url: str, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw) if raw else {}
            return (data if isinstance(data, dict) else {}), int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        detail_raw = ""
        try:
            detail_raw = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail_raw = ""
        try:
            data = json.loads(detail_raw) if detail_raw else {}
        except Exception:
            data = {"error": f"http_{exc.code}", "detail": detail_raw}
        return (data if isinstance(data, dict) else {"error": f"http_{exc.code}"}), int(exc.code)


def _api_get_json_or_error(base_url: str, path: str) -> tuple[dict[str, Any], str]:
    try:
        return _api_get_json(base_url, path), ""
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        try:
            payload = json.loads(detail) if detail else {}
        except Exception:
            payload = {}
        code = str(payload.get("error", "") or f"http_{exc.code}") if isinstance(payload, dict) else f"http_{exc.code}"
        return {}, code


def _clip(s: str, n: int) -> str:
    text = str(s or "")
    return text if len(text) <= n else text[:n]


def _norm(text: str) -> str:
    return "".join(ch.lower() for ch in str(text or "").strip() if ch.isalnum() or ch == "_")


def _resolve_library_scope(base_url: str, library_id_arg: str = "") -> tuple[list[str], str]:
    explicit = str(library_id_arg or "").strip()
    libs_payload = _api_get_json(base_url, "/literature/libraries")
    libs = libs_payload.get("libraries", [])
    if not isinstance(libs, list):
        libs = []
    known: dict[str, str] = {}
    for item in libs:
        if not isinstance(item, dict):
            continue
        lid = str(item.get("library_id", "") or "").strip()
        ws = str(item.get("workspace_path", "") or "").strip()
        if lid:
            known[lid] = ws
    if explicit:
        if explicit not in known:
            raise RuntimeError(f"library_not_found:library_id={explicit}")
        return [explicit], explicit

    from kn_graph.config import Settings
    boot = Settings()
    boot.load_global_settings()
    root_ws = boot.workspaces_dir.resolve()
    cwd = Path.cwd().resolve()

    if cwd == root_ws:
        ids = sorted(known.keys())
        return ids, "all"
    try:
        rel = cwd.relative_to(root_ws)
        parts = rel.parts
        if parts:
            first = parts[0]
            if first in known:
                return [first], first
        return sorted(known.keys()), "all"
    except ValueError:
        # Not under root workspace: use default library if available.
        default_id = str(libs_payload.get("default_library_id", "") or "").strip()
        if default_id and default_id in known:
            return [default_id], default_id
        ids = sorted(known.keys())
        if ids:
            return [ids[0]], ids[0]
        raise RuntimeError("library_not_found:no_library_registered")


def _normalize_weights(vector_weight: Any) -> tuple[float, float]:
    if vector_weight is None or str(vector_weight).strip() == "":
        vw = 0.6
    else:
        vw = float(vector_weight)
    if vw < 0:
        vw = 0.0
    if vw > 1:
        vw = 1.0
    kw = 1.0 - vw
    s = vw + kw
    if s <= 0:
        return 0.6, 0.4
    return vw / s, kw / s


def _coerce_top_k(raw: Any) -> int:
    k = int(raw or 3)
    if k < 3:
        return 3
    if k > 20:
        return 20
    return k


def _safe_float(item: dict[str, Any], keys: list[str]) -> float:
    for k in keys:
        if k not in item:
            continue
        try:
            return float(item.get(k) or 0.0)
        except Exception:
            continue
    return 0.0


def _tokenize(text: str) -> list[str]:
    return [t for t in re_split_nonword(str(text or "").lower()) if t]


def re_split_nonword(text: str) -> list[str]:
    import re as _re
    return _re.split(r"[^\w]+", text)


def _hash_embedding(text: str, dim: int = 256) -> list[float]:
    import hashlib
    bins = [0.0] * dim
    for tok in _tokenize(text):
        h = hashlib.md5(tok.encode("utf-8", errors="ignore")).hexdigest()
        idx = int(h[:8], 16) % dim
        sign = -1.0 if (int(h[8:10], 16) % 2) else 1.0
        bins[idx] += sign
    norm = sum(x * x for x in bins) ** 0.5
    if norm > 0:
        bins = [x / norm for x in bins]
    return bins


def _dot(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def _paper_path_from_hit(item: dict[str, Any]) -> str:
    ctx = item.get("context") if isinstance(item.get("context"), dict) else {}
    paragraph = ctx.get("paragraph") if isinstance(ctx.get("paragraph"), dict) else {}
    document = ctx.get("document") if isinstance(ctx.get("document"), dict) else {}
    for key in ("source_pdf_path", "source_md_path", "source_html_path", "source_html", "offline_html_path"):
        val = str(paragraph.get(key, "") or document.get(key, "") or "").strip()
        if val:
            return val
    return ""


def _truncate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["truncated"] = False
    out.setdefault("truncate_reason", "")

    # First pass: clip large text fields.
    if isinstance(out.get("hits"), list):
        for h in out["hits"]:
            if not isinstance(h, dict):
                continue
            h["sentence_text"] = _clip(str(h.get("sentence_text", "") or ""), MAX_TEXT_SENTENCE)
            h["paragraph_text"] = _clip(str(h.get("paragraph_text", "") or ""), MAX_TEXT_PARAGRAPH)

    cur = json.dumps(out, ensure_ascii=False)
    if len(cur) <= MAX_RETURN_CHARS:
        return out

    # Second pass: shrink list tails by score order.
    for key in ("hits", "candidates", "upstream", "downstream"):
        arr = out.get(key)
        if not isinstance(arr, list):
            continue
        while len(arr) > 1 and len(json.dumps(out, ensure_ascii=False)) > MAX_RETURN_CHARS:
            arr.pop()

    if len(json.dumps(out, ensure_ascii=False)) > MAX_RETURN_CHARS:
        # Final safety clip on message-ish fields.
        for key in ("error_message",):
            if key in out:
                out[key] = _clip(str(out.get(key, "") or ""), 280)

    out["truncated"] = True
    out["truncate_reason"] = "max_chars_exceeded"
    return out


def _error(code: str, message: str, detail: str = "") -> dict[str, Any]:
    out = {
        "ok": False,
        "error_code": str(code or "internal_error"),
        "error_message": str(message or ""),
    }
    if detail:
        out["error_detail"] = detail
    return out


def _build_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "rag_search",
            "description": (
                "Search ChromaDB evidence with hybrid retrieval. Returns up to top_k keyword hits plus up to top_k "
                "vector/rag hits, each with sentence/paragraph + paper absolute path."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "vector_weight": {"type": "number", "minimum": 0, "maximum": 1},
                    "top_k": {"type": "integer", "minimum": 3, "maximum": 20},
                    "library_id": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "graph_variable_neighbors",
            "description": (
                "Find upstream/downstream neighbors for real KG variable nodes only. "
                "Semantic mode first recalls concept candidates, then filters to candidates with an actual KG node; "
                "definition-only concept matches return variable_not_found."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variable_name": {"type": "string"},
                    "mode": {"type": "string", "enum": ["exact", "semantic"]},
                    "vector_weight": {"type": "number", "minimum": 0, "maximum": 1},
                    "top_k": {"type": "integer", "minimum": 3, "maximum": 20},
                    "library_id": {"type": "string"},
                },
                "required": ["variable_name", "mode"],
            },
        },
        {
            "name": "graph_variable_concept_search",
            "description": (
                "Search variable concept candidates. Results may be definition-only; check in_kg and kg_node_id "
                "before using graph_variable_neighbors."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 3, "maximum": 20},
                    "library_id": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "library_import_submit_batch",
            "description": "Batch submit local PDF paths into literature libraries via pipeline.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "library_id": {"type": "string"},
                                "pdf_path": {"type": "string"},
                                "options": {"type": "object"},
                            },
                            "required": ["library_id", "pdf_path"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
        {
            "name": "library_import_query_batch",
            "description": "Batch query pipeline job statuses by job_ids.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["job_ids"],
            },
        },
    ]


def _handle_rag_search(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return _error("invalid_args", "query is required")
    top_k = _coerce_top_k(arguments.get("top_k", 8))
    vw, kw = _normalize_weights(arguments.get("vector_weight"))
    try:
        library_ids, scope = _resolve_library_scope(base_url, str(arguments.get("library_id", "") or ""))
    except Exception as exc:
        return _error("library_not_found", "failed to resolve library scope", str(exc))

    merged_rows: list[dict[str, Any]] = []
    for lid in library_ids:
        try:
            payload = _api_get_json(
                base_url,
                f"/literature/search?query={quote(query)}&top_k={top_k}&levels=sentence"
                f"&include_expanded_context=true&library_id={quote(lid)}&keyword_weight={kw:.6f}&rag_weight={vw:.6f}",
            )
        except Exception as exc:
            return _error("backend_timeout", f"literature search failed for library {lid}", str(exc))
        for route_key, route_name in (("keyword_hits", "keyword"), ("rag_hits", "rag")):
            hits = payload.get(route_key, []) if isinstance(payload, dict) else []
            if not isinstance(hits, list):
                continue
            for item in hits[:top_k]:
                if not isinstance(item, dict):
                    continue
                ctx = item.get("context") if isinstance(item.get("context"), dict) else {}
                paragraph = ctx.get("paragraph") if isinstance(ctx.get("paragraph"), dict) else {}
                sentence = ctx.get("sentence") if isinstance(ctx.get("sentence"), dict) else {}
                sentence_text = str(sentence.get("text", "") or item.get("text", "") or "").strip()
                paragraph_text = str(paragraph.get("text", "") or "").strip()
                if not sentence_text and not paragraph_text:
                    continue
                merged_rows.append(
                    {
                        "route": str(item.get("route", "") or route_name),
                        "level": str(item.get("level", "") or "sentence"),
                        "score": _safe_float(item, ["score", "rrf_score", "final_score"]),
                        "sentence_text": sentence_text,
                        "paragraph_text": paragraph_text,
                        "paper_path_abs": _paper_path_from_hit(item),
                        "paper_id": str(item.get("paper_id", "") or ""),
                        "library_id": lid,
                    }
                )
    if not merged_rows:
        return _error("no_hits", "no evidence hits found")

    out = {
        "ok": True,
        "query": query,
        "library_scope": scope,
        "weights": {"vector": round(vw, 6), "keyword": round(kw, 6)},
        "top_k": top_k,
        "return_mode": "keyword_top_k_plus_vector_top_k",
        "total_returned": len(merged_rows),
        "hits": merged_rows,
    }
    return _truncate_payload(out)


def _lookup_variable_candidates(
    base_url: str,
    variable_name: str,
    mode: str,
    vector_weight: float,
    keyword_weight: float,
    top_k: int,
    library_ids: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    needle = _norm(variable_name)
    for lid in library_ids:
        payload = _api_get_json(
            base_url,
            f"/graph/search?mode=variable&query={quote(variable_name)}&limit={top_k}"
            f"&keyword_weight={keyword_weight:.6f}&vector_weight={vector_weight:.6f}&vector_backend=hash&library_id={quote(lid)}",
        )
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "") or "")
            rid = str(row.get("id", "") or row.get("node_id", "") or "").strip()
            if not rid:
                continue
            if mode == "exact":
                if _norm(title) != needle and _norm(rid.split("::")[-1]) != needle:
                    continue
            candidates.append(
                {
                    "variable_id": rid,
                    "variable_name": title or rid,
                    "library_id": str(row.get("library_id", "") or lid),
                    "score": _safe_float(row, ["score"]),
                    "raw": row,
                }
            )
    candidates.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return candidates[:top_k]


def _resolve_exact_kg_variable(
    base_url: str,
    alias_candidates: list[str],
    library_id: str,
    top_k: int,
) -> dict[str, Any]:
    for alias in alias_candidates:
        exact = _lookup_variable_candidates(base_url, alias, "exact", 0.0, 1.0, top_k, [library_id])
        if exact:
            return exact[0]
    return {}


def _lookup_variable_concept_candidates(
    base_url: str,
    variable_name: str,
    top_k: int,
    library_ids: list[str],
) -> list[dict[str, Any]]:
    try:
        ws_map = _library_workspace_map(base_url)
    except Exception:
        ws_map = {}
    out: list[dict[str, Any]] = []
    for lid in library_ids:
        workspace_path = str(ws_map.get(lid, "") or "").strip()
        if not workspace_path:
            continue
        service = VariableConceptIndexService(workspace_path=workspace_path)
        hits = service.query(library_id=lid, query=variable_name, top_k=top_k)
        canonical_ids = list(
            dict.fromkeys(str(h.get("canonical_var_id", "") or "").strip() for h in hits if isinstance(h, dict))
        )
        canonical_ids = [x for x in canonical_ids if x]
        db_path = str((Path(workspace_path).resolve() / "kn_gragh.db"))
        alias_map = service.expand_aliases(db_path=db_path, canonical_var_ids=canonical_ids) if canonical_ids else {}
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            vname = str(hit.get("variable_name", "") or "").strip()
            if not vname:
                continue
            cid = str(hit.get("canonical_var_id", "") or "").strip()
            alias_candidates = [vname, *[str(a) for a in alias_map.get(cid, []) if str(a).strip()]]
            alias_candidates = list(dict.fromkeys([x.strip() for x in alias_candidates if x.strip()]))
            resolved = _resolve_exact_kg_variable(base_url, alias_candidates, lid, top_k)
            if not resolved:
                continue
            out.append(
                {
                    "variable_id": str(resolved.get("variable_id", "") or ""),
                    "variable_name": str(resolved.get("variable_name", "") or vname),
                    "library_id": str(hit.get("library_id", "") or lid),
                    "score": float(hit.get("score", 0.0) or 0.0),
                    "concept_text": str(hit.get("concept_text", "") or ""),
                }
            )
    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out[:top_k]


def _lookup_variable_alias_exact_candidates(
    base_url: str,
    variable_name: str,
    top_k: int,
    library_ids: list[str],
) -> list[dict[str, Any]]:
    needle = _norm(variable_name)
    try:
        ws_map = _library_workspace_map(base_url)
    except Exception:
        ws_map = {}
    out: list[dict[str, Any]] = []
    for lid in library_ids:
        workspace_path = str(ws_map.get(lid, "") or "").strip()
        if not workspace_path:
            continue
        service = VariableConceptIndexService(workspace_path=workspace_path)
        hits = service.query(library_id=lid, query=variable_name, top_k=max(top_k, 20))
        canonical_ids = list(
            dict.fromkeys(str(h.get("canonical_var_id", "") or "").strip() for h in hits if isinstance(h, dict))
        )
        canonical_ids = [x for x in canonical_ids if x]
        db_path = str((Path(workspace_path).resolve() / "kn_gragh.db"))
        alias_map = service.expand_aliases(db_path=db_path, canonical_var_ids=canonical_ids) if canonical_ids else {}
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            vname = str(hit.get("variable_name", "") or "").strip()
            cid = str(hit.get("canonical_var_id", "") or "").strip()
            alias_candidates = [vname, *[str(a) for a in alias_map.get(cid, []) if str(a).strip()]]
            alias_candidates = list(dict.fromkeys([x.strip() for x in alias_candidates if x.strip()]))
            if not any(_norm(alias) == needle for alias in alias_candidates):
                continue
            resolved = _resolve_exact_kg_variable(base_url, alias_candidates, lid, top_k)
            if resolved:
                out.append(
                    {
                        "variable_id": str(resolved.get("variable_id", "") or ""),
                        "variable_name": str(resolved.get("variable_name", "") or vname),
                        "library_id": str(resolved.get("library_id", "") or lid),
                        "score": float(resolved.get("score", 1.0) or 1.0),
                        "concept_text": str(hit.get("concept_text", "") or ""),
                    }
                )
    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out[:top_k]


def _variable_primary_path(base_url: str, variable_id: str, library_id: str) -> str:
    try:
        payload = _api_get_json(base_url, f"/variable/{quote(variable_id)}?library_id={quote(library_id)}")
    except Exception:
        return ""
    pgs = payload.get("paper_groups", []) if isinstance(payload, dict) else []
    if not isinstance(pgs, list):
        return ""
    for pg in pgs:
        if not isinstance(pg, dict):
            continue
        paper_id = str(pg.get("paper_id", "") or "").strip()
        if not paper_id:
            continue
        try:
            paper = _api_get_json(base_url, f"/paper/{quote(paper_id)}?library_id={quote(library_id)}")
        except Exception:
            paper = {}
        for key in ("source_pdf_path", "source_md_path", "source_html_path", "offline_html_path"):
            val = str(paper.get(key, "") or "").strip()
            if val:
                return val
    return ""


def _variable_concept_text(base_url: str, variable_id: str, library_id: str) -> str:
    try:
        payload = _api_get_json(base_url, f"/variable/{quote(variable_id)}?library_id={quote(library_id)}")
    except Exception:
        return ""
    pgs = payload.get("paper_groups", []) if isinstance(payload, dict) else []
    if not isinstance(pgs, list):
        return ""
    for pg in pgs:
        if not isinstance(pg, dict):
            continue
        concepts = pg.get("concepts", [])
        if not isinstance(concepts, list):
            continue
        for c in concepts:
            if not isinstance(c, dict):
                continue
            txt = str(c.get("definition", "") or "").strip()
            if txt:
                return txt
    return ""


def _relation_between(current_id: str, other_id: str, edges: list[dict[str, Any]]) -> str:
    if current_id == other_id:
        return "self"
    for e in edges:
        if not isinstance(e, dict):
            continue
        s = str(e.get("source", "") or e.get("source_node_id", "") or "").strip()
        t = str(e.get("target", "") or e.get("target_node_id", "") or "").strip()
        if s == other_id and t == current_id:
            return "upstream"
        if s == current_id and t == other_id:
            return "downstream"
    return "unrelated_in_1hop"


def _handle_graph_variable_neighbors(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    variable_name = str(arguments.get("variable_name", "") or "").strip()
    mode = str(arguments.get("mode", "") or "").strip().lower()
    if not variable_name:
        return _error("invalid_args", "variable_name is required")
    if mode not in {"exact", "semantic"}:
        return _error("invalid_args", "mode must be exact or semantic")
    top_k = _coerce_top_k(arguments.get("top_k", 3))
    vw, kw = _normalize_weights(arguments.get("vector_weight"))
    try:
        library_ids, scope = _resolve_library_scope(base_url, str(arguments.get("library_id", "") or ""))
    except Exception as exc:
        return _error("library_not_found", "failed to resolve library scope", str(exc))

    try:
        if mode == "exact":
            candidates = _lookup_variable_candidates(base_url, variable_name, mode, vw, kw, top_k, library_ids)
            if not candidates:
                candidates = _lookup_variable_alias_exact_candidates(base_url, variable_name, top_k, library_ids)
        else:
            candidates = _lookup_variable_concept_candidates(base_url, variable_name, top_k, library_ids)
    except Exception as exc:
        return _error("internal_error", "graph variable search failed", str(exc))
    if not candidates:
        return _error("variable_not_found", f"no variable matched '{variable_name}'")

    current: dict[str, Any] = {}
    neigh: dict[str, Any] = {}
    skipped: list[str] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("variable_id", "") or "")
        candidate_lib = str(candidate.get("library_id", "") or "")
        payload, err = _api_get_json_or_error(
            base_url,
            f"/graph/neighborhood?node_id={quote(candidate_id)}&hops=1&limit_nodes=120&limit_edges=240&library_id={quote(candidate_lib)}",
        )
        if not err:
            current = candidate
            neigh = payload
            break
        if err == "node_not_found":
            skipped.append(candidate_id)
            continue
        return _error("graph_not_built", "failed to query graph neighborhood", err)
    if not current:
        detail = "; skipped missing KG nodes: " + ", ".join(skipped[:8]) if skipped else ""
        return _error("variable_not_found", f"no KG variable node matched '{variable_name}'{detail}")
    current_id = str(current.get("variable_id", "") or "")
    current_lib = str(current.get("library_id", "") or "")
    nodes = neigh.get("nodes", []) if isinstance(neigh, dict) else []
    edges = neigh.get("edges", []) if isinstance(neigh, dict) else []
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    node_map: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", "") or "").strip()
        if nid:
            node_map[nid] = n

    upstream: list[dict[str, Any]] = []
    downstream: list[dict[str, Any]] = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source", "") or e.get("source_node_id", "") or "").strip()
        tgt = str(e.get("target", "") or e.get("target_node_id", "") or "").strip()
        rel = str(e.get("relation", "") or e.get("effect_form", "") or "related").strip()
        if tgt == current_id and src and src in node_map and str(node_map[src].get("type", "")) == "variable":
            upstream.append(
                {
                    "variable_name": str(node_map[src].get("label", "") or node_map[src].get("name", "") or src),
                    "relation": rel,
                    "score": 1.0,
                    "paper_path_abs": _variable_primary_path(base_url, src, current_lib),
                    "paper_id": str(node_map[src].get("dominant_paper_id", "") or ""),
                }
            )
        elif src == current_id and tgt and tgt in node_map and str(node_map[tgt].get("type", "")) == "variable":
            downstream.append(
                {
                    "variable_name": str(node_map[tgt].get("label", "") or node_map[tgt].get("name", "") or tgt),
                    "relation": rel,
                    "score": 1.0,
                    "paper_path_abs": _variable_primary_path(base_url, tgt, current_lib),
                    "paper_id": str(node_map[tgt].get("dominant_paper_id", "") or ""),
                }
            )
    upstream.sort(key=lambda x: str(x.get("variable_name", "")))
    downstream.sort(key=lambda x: str(x.get("variable_name", "")))

    current_path = _variable_primary_path(base_url, current_id, current_lib)
    current_concept = str(current.get("concept_text", "") or _variable_concept_text(base_url, current_id, current_lib))
    todos: list[str] = []
    if mode == "semantic" and not current_concept:
        todos.append("TODO: current_variable_concept_embedding_missing")

    cand_out: list[dict[str, Any]] = []
    for c in candidates:
        cid = str(c.get("variable_id", "") or "")
        clib = str(c.get("library_id", "") or "")
        cand_out.append(
            {
                "variable_id": cid,
                "variable_name": str(c.get("variable_name", "") or cid),
                "library_id": clib,
                "score": float(c.get("score", 0.0)),
                "concept_text": str(c.get("concept_text", "") or _variable_concept_text(base_url, cid, clib)),
                "relation_to_current": _relation_between(current_id, cid, edges),
            }
        )

    out = {
        "ok": True,
        "library_scope": scope,
        "query_variable": variable_name,
        "query_variable_path_abs": current_path,
        "match_mode": mode,
        "weights": {"vector": round(vw, 6), "keyword": round(kw, 6)},
        "matched_variable": {
            "variable_id": current_id,
            "variable_name": str(current.get("variable_name", "") or current_id),
            "library_id": current_lib,
            "score": float(current.get("score", 0.0)),
            "concept_text": current_concept,
        },
        "candidates": cand_out,
        "upstream": sorted(upstream, key=lambda x: float(x.get("score", 0.0)), reverse=True)[:top_k],
        "downstream": sorted(downstream, key=lambda x: float(x.get("score", 0.0)), reverse=True)[:top_k],
        "todos": todos,
    }
    return _truncate_payload(out)


def _library_workspace_map(base_url: str) -> dict[str, str]:
    payload = _api_get_json(base_url, "/literature/libraries")
    libs = payload.get("libraries", []) if isinstance(payload, dict) else []
    if not isinstance(libs, list):
        return {}
    out: dict[str, str] = {}
    for item in libs:
        if not isinstance(item, dict):
            continue
        lid = str(item.get("library_id", "") or "").strip()
        ws = str(item.get("workspace_path", "") or "").strip()
        if lid and ws:
            out[lid] = ws
    return out


def _handle_graph_variable_concept_search(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return _error("invalid_args", "query is required")
    top_k = _coerce_top_k(arguments.get("top_k", 5))
    try:
        library_ids, scope = _resolve_library_scope(base_url, str(arguments.get("library_id", "") or ""))
    except Exception as exc:
        return _error("library_not_found", "failed to resolve library scope", str(exc))

    try:
        ws_map = _library_workspace_map(base_url)
    except Exception as exc:
        return _error("internal_error", "failed to resolve library workspace", str(exc))

    matched_variables: list[dict[str, Any]] = []
    paper_map: dict[str, dict[str, str]] = {}
    trace_libraries: list[dict[str, Any]] = []
    neighborhood_cache: dict[tuple[str, str], dict[str, Any]] = {}

    for lid in library_ids:
        workspace_path = str(ws_map.get(lid, "") or "").strip()
        if not workspace_path:
            return _error("library_not_found", "failed to resolve library workspace", f"workspace_path_missing:library_id={lid}")
        db_path = str((Path(workspace_path).resolve() / "kn_gragh.db"))
        service = VariableConceptIndexService(workspace_path=workspace_path)
        try:
            hits = service.query(library_id=lid, query=query, top_k=top_k)
        except Exception as exc:
            return _error("internal_error", f"variable concept query failed for library {lid}", str(exc))

        canonical_ids = list(
            dict.fromkeys(str(h.get("canonical_var_id", "") or "").strip() for h in hits if isinstance(h, dict))
        )
        canonical_ids = [x for x in canonical_ids if x]
        try:
            alias_map = service.expand_aliases(db_path=db_path, canonical_var_ids=canonical_ids) if canonical_ids else {}
        except Exception as exc:
            return _error("internal_error", f"failed to expand aliases for library {lid}", str(exc))

        trace_libraries.append(
            {
                "library_id": lid,
                "workspace_path": workspace_path,
                "db_path": db_path,
                "hit_count": len(hits),
                "canonical_var_count": len(canonical_ids),
            }
        )

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            variable_name = str(hit.get("variable_name", "") or "")
            cid = str(hit.get("canonical_var_id", "") or "").strip()
            pid = str(hit.get("paper_id", "") or "").strip()
            aliases = alias_map.get(cid, []) if cid else []
            alias_candidates = [variable_name, *[str(a) for a in aliases if str(a).strip()]]
            alias_candidates = list(dict.fromkeys([x.strip() for x in alias_candidates if x.strip()]))
            kg_node = _resolve_exact_kg_variable(base_url, alias_candidates, lid, top_k=max(top_k, 20))
            kg_node_id = str(kg_node.get("variable_id", "") or "")

            merged_cause: list[dict[str, Any]] = []
            merged_effect: list[dict[str, Any]] = []
            seen_cause: set[str] = set()
            seen_effect: set[str] = set()

            for candidate in alias_candidates:
                cache_key = (lid, candidate.strip().lower())
                if cache_key not in neighborhood_cache:
                    neigh_resp = _handle_graph_variable_neighbors(
                        base_url,
                        {
                            "variable_name": candidate,
                            "mode": "exact",
                            "top_k": max(top_k, 20),
                            "library_id": lid,
                        },
                    )
                    if isinstance(neigh_resp, dict) and bool(neigh_resp.get("ok")):
                        neighborhood_cache[cache_key] = {
                            "cause_variables": neigh_resp.get("upstream", []) if isinstance(neigh_resp.get("upstream"), list) else [],
                            "effect_variables": neigh_resp.get("downstream", []) if isinstance(neigh_resp.get("downstream"), list) else [],
                        }
                    else:
                        neighborhood_cache[cache_key] = {"cause_variables": [], "effect_variables": []}
                neighborhood = neighborhood_cache.get(cache_key, {"cause_variables": [], "effect_variables": []})
                for row in neighborhood.get("cause_variables", []):
                    if not isinstance(row, dict):
                        continue
                    key = f"{str(row.get('variable_name','')).strip().lower()}::{str(row.get('relation','')).strip().lower()}"
                    if key in seen_cause:
                        continue
                    seen_cause.add(key)
                    merged_cause.append(row)
                for row in neighborhood.get("effect_variables", []):
                    if not isinstance(row, dict):
                        continue
                    key = f"{str(row.get('variable_name','')).strip().lower()}::{str(row.get('relation','')).strip().lower()}"
                    if key in seen_effect:
                        continue
                    seen_effect.add(key)
                    merged_effect.append(row)
            matched_variables.append(
                {
                    "id": str(hit.get("id", "") or ""),
                    "score": float(hit.get("score", 0.0) or 0.0),
                    "library_id": str(hit.get("library_id", "") or lid),
                    "paper_id": pid,
                    "variable_name": variable_name,
                    "canonical_var_id": cid,
                    "kg_node_id": kg_node_id,
                    "in_kg": bool(kg_node_id),
                    "aliases": aliases,
                    "concept_text": str(hit.get("concept_text", "") or ""),
                    "cause_variables": merged_cause,
                    "effect_variables": merged_effect,
                }
            )
            if pid:
                paper_map[f"{lid}::{pid}"] = {"library_id": lid, "paper_id": pid}

    if not matched_variables:
        return _error("no_hits", "no variable concept hits found")

    matched_variables.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    papers = list(paper_map.values())
    out = {
        "ok": True,
        "query": query,
        "top_k": top_k,
        "library_scope": scope,
        "matched_variables": matched_variables,
        "papers": papers,
        "trace": {
            "libraries": trace_libraries,
            "library_count": len(library_ids),
        },
    }
    return _truncate_payload(out)


def _handle_pipeline_import_batch_submit(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    items = arguments.get("items", [])
    if not isinstance(items, list) or not items:
        return _error("invalid_args", "items is required")
    payload, status = _api_post_json(base_url, "/v1/pipeline/parse-extract/path-batch", {"items": items})
    ok = status < 400 and int(payload.get("accepted_count", 0) or 0) > 0
    out = {
        "ok": ok,
        "http_status": status,
        "accepted_count": int(payload.get("accepted_count", 0) or 0),
        "rejected_count": int(payload.get("rejected_count", 0) or 0),
        "accepted": payload.get("accepted", []) if isinstance(payload.get("accepted"), list) else [],
        "rejected": payload.get("rejected", []) if isinstance(payload.get("rejected"), list) else [],
    }
    if not ok and not out["rejected"]:
        out["error_code"] = str(payload.get("error", "") or f"http_{status}")
        out["error_message"] = str(payload.get("message", "") or "batch submit failed")
    return _truncate_payload(out)


def _handle_pipeline_import_batch_status(base_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    job_ids = arguments.get("job_ids", [])
    if not isinstance(job_ids, list) or not job_ids:
        return _error("invalid_args", "job_ids is required")
    payload, status = _api_post_json(base_url, "/v1/jobs/batch-status", {"job_ids": job_ids})
    if status >= 400:
        return _error(str(payload.get("error", "") or f"http_{status}"), "batch status failed", json.dumps(payload, ensure_ascii=False))
    jobs = payload.get("jobs", []) if isinstance(payload.get("jobs"), list) else []
    return _truncate_payload(
        {
            "ok": True,
            "total": int(payload.get("total", len(jobs)) or len(jobs)),
            "jobs": jobs,
        }
    )


def _call_tool(base_url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "rag_search":
        return _handle_rag_search(base_url, arguments)
    if name == "graph_variable_neighbors":
        return _handle_graph_variable_neighbors(base_url, arguments)
    if name == "graph_variable_concept_search":
        return _handle_graph_variable_concept_search(base_url, arguments)
    if name == "library_import_submit_batch":
        return _handle_pipeline_import_batch_submit(base_url, arguments)
    if name == "library_import_query_batch":
        return _handle_pipeline_import_batch_status(base_url, arguments)
    return _error("tool_not_found", f"tool not found: {name}")


def _tool_result_text(obj: dict[str, Any], cap: int = MAX_RETURN_CHARS) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= cap else text[:cap]


def main() -> None:
    from kn_graph.config import Settings

    boot = Settings()
    boot.load_global_settings()
    default_url = str(os.getenv("KN_GRAPH_API_BASE_URL", "") or "").strip() or f"http://{boot.host}:{boot.port}"

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
                        "serverInfo": {"name": "kn_graph_tools", "version": "0.2.0"},
                        "capabilities": {"tools": {}},
                    },
                }
            )
            continue

        if method == "tools/list":
            _write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})
            continue

        if method == "tools/call":
            name = str(params.get("name", "") or "").strip()
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            result = _call_tool(base_url, name, arguments)
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": _tool_result_text(result)}],
                        "structuredContent": result,
                        "isError": not bool(result.get("ok", False)) if isinstance(result, dict) else True,
                    },
                }
            )
            continue

        _write({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method_not_found:{method}"}})


if __name__ == "__main__":
    main()
