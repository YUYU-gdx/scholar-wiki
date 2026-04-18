from __future__ import annotations

import argparse
from collections import deque
import json
import importlib.util
import math
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUPPLY_CHAIN_ROOT = Path("outputs/smj_supply_chain_batch").resolve()
SUPPLY_CHAIN_DEFAULT_VIEWS = Path(
    "outputs/smj_supply_chain_batch/supply_chain_merged_20260414_113031/graph_views.json"
)


def _load_env_utils():
    module_path = Path(__file__).resolve().parent / "env_utils.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_env_utils_for_serve_graph_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENV_UTILS = _load_env_utils()


def _resolve_views_json(cli_views_json: Path | None, runs_root: Path) -> Path:
    if cli_views_json is not None:
        return cli_views_json
    active_path = runs_root / "active.json"
    if not active_path.exists():
        return SUPPLY_CHAIN_DEFAULT_VIEWS
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid active json: {active_path}")
    graph_views = str(payload.get("graph_views", "")).strip()
    if not graph_views:
        raise RuntimeError(f"active json missing graph_views: {active_path}")
    return Path(graph_views)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Serve graph API and static frontend.")
    p.add_argument("--views-json", type=Path, default=None)
    p.add_argument("--frontend-dir", type=Path, default=Path("outputs/smj_batch_full/frontend"))
    p.add_argument("--runs-root", type=Path, default=Path("outputs/runs"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8013)
    p.add_argument("--allow-non-supply-chain", action="store_true")
    return p.parse_args()


def _enforce_supply_chain_path(path: Path, allow_non_supply_chain: bool) -> None:
    resolved = path.resolve()
    if allow_non_supply_chain:
        return
    if SUPPLY_CHAIN_ROOT not in resolved.parents and resolved != SUPPLY_CHAIN_ROOT:
        raise RuntimeError(
            f"views path is outside supply-chain scope: {resolved}\n"
            f"allowed root: {SUPPLY_CHAIN_ROOT}\n"
            "use --allow-non-supply-chain to override explicitly"
        )


def _json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _guess_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".html":
        return "text/html; charset=utf-8"
    if ext == ".js":
        return "text/javascript; charset=utf-8"
    if ext == ".css":
        return "text/css; charset=utf-8"
    if ext == ".json":
        return "application/json; charset=utf-8"
    return "application/octet-stream"


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for ch in (text or "").lower():
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return out


def _hash_embedding(text: str, dim: int = 128) -> list[float]:
    vec = [0.0] * dim
    for tok in _tokenize(text):
        idx = hash(tok) % dim
        sign = -1.0 if (hash(tok + "::s") & 1) else 1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def _dot(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def _norm_rel_text(text: str) -> str:
    return " ".join(_tokenize(text or ""))


def _paper_links(p: dict[str, Any], pid: str) -> tuple[str, str]:
    local_html = str(p.get("offline_html_path", "") or "").strip()
    online_url = str(p.get("article_url", "") or "").strip()
    doi = str(p.get("doi", "") or pid).strip()
    if not online_url and doi:
        online_url = f"https://sms.onlinelibrary.wiley.com/doi/full/{doi}"
    return local_html, online_url


def _relation_summary_from_mention(m: dict[str, Any]) -> dict[str, Any]:
    kind = str(m.get("mention_kind", "edge") or "edge")
    if kind == "interaction":
        return {
            "kind": "interaction",
            "title": f"{str(m.get('source_name', '') or '').strip()} -> {str(m.get('target_name', '') or '').strip()}",
            "direction": str(m.get("direction", "") or "").strip(),
            "relation_form": "interaction",
            "relation_type": str(m.get("relation_type_std", "interaction") or "interaction"),
            "evidence_section": str(m.get("evidence_section", "") or "").strip(),
        }
    if kind == "moderation":
        moderator = str(m.get("moderator_name", "") or "").strip()
        src = str(m.get("source_name", "") or "").strip()
        tgt = str(m.get("target_name", "") or "").strip()
        return {
            "kind": "moderation",
            "title": f"{moderator} 调节 {src} -> {tgt}",
            "direction": str(m.get("direction", "") or "").strip(),
            "relation_form": str(m.get("relation_form", "linear") or "linear"),
            "relation_type": "moderation",
            "evidence_section": str(m.get("evidence_section", "") or "").strip(),
        }
    src = str(m.get("source_name", "") or "").strip()
    tgt = str(m.get("target_name", "") or "").strip()
    return {
        "kind": "direct_effect",
        "title": f"{src} -> {tgt}",
        "direction": str(m.get("direction", "") or "").strip(),
        "relation_form": str(m.get("relation_form", "") or "").strip(),
        "relation_type": str(m.get("relation_type_std", "") or "").strip(),
        "evidence_section": str(m.get("evidence_section", "") or "").strip(),
    }


def make_handler(views: dict[str, Any], frontend_dir: Path):
    nodes: dict[str, dict[str, Any]] = views["nodes"]
    edges: list[dict[str, Any]] = views["edges"]
    moderation_links: list[dict[str, Any]] = views.get("moderation_links", [])
    interaction_links: list[dict[str, Any]] = views.get("interaction_links", [])
    edge_index_by_node: dict[str, list[int]] = views["edge_index_by_node"]
    overview = views["overview"]
    paper_map: dict[str, dict[str, Any]] = views["paper_map"]
    meta = views.get("meta", {})
    paper_map_unique: dict[str, dict[str, Any]] = {}
    for p in paper_map.values():
        if not isinstance(p, dict):
            continue
        pid = str(p.get("paper_id", "")).strip()
        if pid and pid not in paper_map_unique:
            paper_map_unique[pid] = p

    node_id_to_name = {
        nid: str(n.get("label") or n.get("name") or nid)
        for nid, n in nodes.items()
    }
    node_mentions: dict[str, list[dict[str, Any]]] = {}
    node_to_papers_edge: dict[str, set[str]] = {}
    node_to_papers_moderation: dict[str, set[str]] = {}
    node_to_papers_interaction: dict[str, set[str]] = {}
    for edge in edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        pid = str(edge.get("paper_id", "")).strip()
        if not source or not target or not pid:
            continue
        mention = {
            "paper_id": pid,
            "doi": str(edge.get("doi", "") or pid),
            "source": source,
            "target": target,
            "source_name": str(edge.get("source_name_local", "") or node_id_to_name.get(source, source)),
            "target_name": str(edge.get("target_name_local", "") or node_id_to_name.get(target, target)),
            "source_name_canonical": node_id_to_name.get(source, source),
            "target_name_canonical": node_id_to_name.get(target, target),
            "direction": str(edge.get("direction", "") or ""),
            "relation_form": str(edge.get("relation_form", "") or ""),
            "relation_type_std": str(edge.get("relation_type_std", "") or str(edge.get("relation_type", "") or "")),
            "relation_type_raw": str(edge.get("relation_type_raw", "") or str(edge.get("relation_type", "") or "")),
            "evidence_section": str(edge.get("evidence_section", "") or ""),
        }
        mention["mention_kind"] = "edge"
        if source != target:
            node_mentions.setdefault(source, []).append(mention)
            node_mentions.setdefault(target, []).append(mention)
            node_to_papers_edge.setdefault(source, set()).add(pid)
            node_to_papers_edge.setdefault(target, set()).add(pid)

    for mod in moderation_links:
        pid = str(mod.get("paper_id", "")).strip()
        if not pid:
            continue
        mr = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
        moderator_node_id = str(mod.get("moderator_node_id", "")).strip()
        src_node_id = str(mr.get("source_node_id", "")).strip()
        tgt_node_id = str(mr.get("target_node_id", "")).strip()
        moderator_name = str(mod.get("moderator_var", "") or node_id_to_name.get(moderator_node_id, moderator_node_id))
        src_name = str(mr.get("source_var", "") or node_id_to_name.get(src_node_id, src_node_id))
        tgt_name = str(mr.get("target_var", "") or node_id_to_name.get(tgt_node_id, tgt_node_id))

        mod_mention = {
            "paper_id": pid,
            "doi": str(mod.get("doi", "") or pid),
            "source": src_node_id,
            "target": tgt_node_id,
            "source_name": src_name,
            "target_name": tgt_name,
            "source_name_canonical": node_id_to_name.get(src_node_id, src_name),
            "target_name_canonical": node_id_to_name.get(tgt_node_id, tgt_name),
            "direction": "",
            "relation_form": "linear",
            "relation_type_std": "moderation",
            "relation_type_raw": "moderation",
            "evidence_section": str(mod.get("evidence_section", "") or ""),
            "mention_kind": "moderation",
            "moderator_node_id": moderator_node_id,
            "moderator_name": moderator_name,
        }

        if moderator_node_id:
            node_mentions.setdefault(moderator_node_id, []).append(mod_mention)
            node_to_papers_moderation.setdefault(moderator_node_id, set()).add(pid)
        if src_node_id and src_node_id != tgt_node_id:
            node_mentions.setdefault(src_node_id, []).append(mod_mention)
            node_to_papers_moderation.setdefault(src_node_id, set()).add(pid)
        if tgt_node_id and src_node_id != tgt_node_id:
            node_mentions.setdefault(tgt_node_id, []).append(mod_mention)
            node_to_papers_moderation.setdefault(tgt_node_id, set()).add(pid)


    for inter in interaction_links:
        pid = str(inter.get("paper_id", "")).strip()
        if not pid:
            continue
        input_ids = [str(v or "").strip() for v in (inter.get("input_node_ids", []) or []) if str(v or "").strip()]
        output_id = str(inter.get("output_node_id", "")).strip()
        interaction_mention = {
            "paper_id": pid,
            "doi": str(inter.get("doi", "") or pid),
            "source": "|".join(input_ids),
            "target": output_id,
            "source_name": " × ".join(str(v or "") for v in (inter.get("inputs", []) or [])),
            "target_name": str(inter.get("output", "") or node_id_to_name.get(output_id, output_id)),
            "source_name_canonical": " × ".join(node_id_to_name.get(nid, nid) for nid in input_ids),
            "target_name_canonical": node_id_to_name.get(output_id, output_id),
            "direction": str(inter.get("effect", "") or ""),
            "relation_form": "interaction",
            "relation_type_std": "interaction",
            "relation_type_raw": str(inter.get("interaction_type", "") or "interaction"),
            "evidence_section": str(inter.get("evidence_section", "") or ""),
            "mention_kind": "interaction",
        }
        for nid in input_ids:
            node_mentions.setdefault(nid, []).append(interaction_mention)
            node_to_papers_interaction.setdefault(nid, set()).add(pid)
        if output_id:
            node_mentions.setdefault(output_id, []).append(interaction_mention)
            node_to_papers_interaction.setdefault(output_id, set()).add(pid)
    # Build local embedding index for variable/paper hybrid search.
    search_items: list[dict[str, Any]] = []
    for nid, node in nodes.items():
        if str(node.get("type", "")) != "variable":
            continue
        mentions = node_mentions.get(nid, [])
        predecessors = sorted({m["source_name"] for m in mentions if m["target"] == nid and m["source"] != nid})[:8]
        successors = sorted({m["target_name"] for m in mentions if m["source"] == nid and m["target"] != nid})[:8]
        paper_ids = sorted(
            node_to_papers_edge.get(nid, set())
            .union(node_to_papers_moderation.get(nid, set()))
            .union(node_to_papers_interaction.get(nid, set()))
        )
        card = {
            "kind": "variable",
            "id": nid,
            "title": str(node.get("label") or node.get("name") or nid),
            "predecessors": predecessors,
            "successors": successors,
            "papers": paper_ids[:20],
        }
        text_blob = " ".join(
            [
                card["title"],
                " ".join(predecessors),
                " ".join(successors),
                " ".join(card["papers"]),
            ]
        )
        search_items.append(
            {
                "mode": "variable",
                "card": card,
                "tokens": set(_tokenize(text_blob)),
                "embedding": _hash_embedding(text_blob),
            }
        )

    for pid, paper in paper_map_unique.items():
        rels = list(paper.get("main_effects", []) or [])
        inters = list(paper.get("interactions", []) or [])
        rel_snippets: list[str] = []
        for r in rels[:20]:
            src = str(r.get("source", "") or r.get("from", "")).strip()
            tgt = str(r.get("target", "") or r.get("to", "")).strip()
            tag = str(r.get("direction", "") or r.get("effect", "") or r.get("relation_type", "")).strip()
            rel_snippets.append(f"{src}->{tgt} {tag}".strip())
        for it in inters[:10]:
            inputs = [str(v or "").strip() for v in (it.get("inputs", []) or []) if str(v or "").strip()]
            output = str(it.get("output", "") or "").strip()
            if len(inputs) >= 2 and output:
                rel_snippets.append(f"{' x '.join(inputs)}->{output} interaction")
        card = {
            "kind": "paper",
            "id": pid,
            "title": str(paper.get("doi", "") or pid),
            "doi": str(paper.get("doi", "") or pid),
            "paper_id": pid,
            "publication_year": paper.get("publication_year"),
            "open_local_html": str(paper.get("offline_html_path", "") or ""),
            "open_online_url": str(paper.get("article_url", "") or (f"https://sms.onlinelibrary.wiley.com/doi/full/{paper.get('doi')}" if paper.get("doi") else "")),
            "relations": rel_snippets[:6],
        }
        text_blob = " ".join([card["title"], " ".join(rel_snippets), " ".join(str(d) for d in paper.get("paper_domains", []) or [])])
        search_items.append(
            {
                "mode": "paper",
                "card": card,
                "tokens": set(_tokenize(text_blob)),
                "embedding": _hash_embedding(text_blob),
            }
        )

    class Handler(BaseHTTPRequestHandler):
        def _serve_static(self, rel_path: str) -> None:
            safe = rel_path.lstrip("/")
            if not safe or safe == "frontend":
                safe = "index.html"
            path = (frontend_dir / safe).resolve()
            if not str(path).startswith(str(frontend_dir.resolve())) or not path.exists() or not path.is_file():
                self.send_error(404, "Not Found")
                return
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _guess_content_type(path))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in ("/", "/frontend", "/frontend/"):
                return self._serve_static("index.html")
            if path.startswith("/frontend/"):
                return self._serve_static(path[len("/frontend/") :])

            if path == "/graph/overview":
                node_ids = overview["node_ids"]
                edge_indexes = overview["edge_indexes"]
                payload = {
                    "meta": meta,
                    "nodes": [nodes[nid] for nid in node_ids if nid in nodes],
                    "edges": [edges[i] for i in edge_indexes if 0 <= i < len(edges)],
                    "moderation_links": moderation_links,
                    "interaction_links": interaction_links,
                }
                return _json(self, payload)

            if path == "/graph/full":
                payload = {
                    "meta": meta,
                    "nodes": list(nodes.values()),
                    "edges": edges,
                    "moderation_links": moderation_links,
                    "interaction_links": interaction_links,
                }
                return _json(self, payload)

            if path == "/graph/search":
                query = (qs.get("query", qs.get("q", [""]))[0] or "").strip().lower()
                mode = (qs.get("mode", ["variable"])[0] or "variable").strip().lower()
                limit = int((qs.get("limit", qs.get("top_k", ["20"]))[0] or "20"))
                keyword_weight = float((qs.get("keyword_weight", ["0.5"])[0] or "0.5"))
                vector_weight = float((qs.get("vector_weight", ["0.5"])[0] or "0.5"))
                requested_backend = (qs.get("vector_backend", ["hash"])[0] or "hash").strip().lower()
                if not query:
                    return _json(self, {"results": [], "search_meta": {"vector_backend_requested": requested_backend, "vector_backend_used": "hash"}})
                q_tokens = set(_tokenize(query))
                q_emb = _hash_embedding(query)
                backend_used = "hash"
                backend_note = ""
                if requested_backend == "embedding":
                    if os.getenv("GRAPH_EMBEDDING_MODEL", "").strip():
                        backend_note = "embedding backend requested but unavailable; fallback to hash."
                    else:
                        backend_note = "embedding model not configured; fallback to hash."
                ranked: list[tuple[float, dict[str, Any]]] = []
                for item in search_items:
                    if item["mode"] != mode:
                        continue
                    kscore = 0.0
                    if q_tokens:
                        overlap = len(q_tokens.intersection(item["tokens"]))
                        kscore = overlap / max(1, len(q_tokens))
                    vscore = (_dot(q_emb, item["embedding"]) + 1.0) / 2.0
                    score = keyword_weight * kscore + vector_weight * vscore
                    if score <= 0:
                        continue
                    payload = dict(item["card"])
                    payload["score"] = round(score, 6)
                    ranked.append((score, payload))
                ranked.sort(key=lambda x: x[0], reverse=True)
                return _json(
                    self,
                    {
                        "results": [p for _, p in ranked[:limit]],
                        "search_meta": {
                            "vector_backend_requested": requested_backend,
                            "vector_backend_used": backend_used,
                            "note": backend_note,
                        },
                    },
                )

            if path == "/graph/neighborhood":
                node_id = (qs.get("node_id", [""])[0] or "").strip()
                hops = int((qs.get("hops", ["1"])[0] or "1"))
                limit_nodes = int((qs.get("limit_nodes", ["350"])[0] or "350"))
                limit_edges = int((qs.get("limit_edges", ["900"])[0] or "900"))
                if node_id not in nodes:
                    return _json(self, {"error": "node_not_found", "node_id": node_id}, status=404)

                seen_nodes = {node_id}
                seen_edges: list[int] = []
                qd: deque[tuple[str, int]] = deque([(node_id, 0)])

                while qd and len(seen_nodes) < limit_nodes and len(seen_edges) < limit_edges:
                    cur, depth = qd.popleft()
                    if depth >= hops:
                        continue
                    for ei in edge_index_by_node.get(cur, []):
                        if ei not in seen_edges:
                            seen_edges.append(ei)
                        e = edges[ei]
                        s = str(e.get("source", ""))
                        t = str(e.get("target", ""))
                        nxt = t if s == cur else s
                        if nxt and nxt not in seen_nodes:
                            seen_nodes.add(nxt)
                            qd.append((nxt, depth + 1))
                        if len(seen_nodes) >= limit_nodes or len(seen_edges) >= limit_edges:
                            break

                seen_node_set = set(seen_nodes)
                neighborhood_mods: list[dict[str, Any]] = []
                for mod in moderation_links:
                    mr = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
                    moderator_node_id = str(mod.get("moderator_node_id", "")).strip()
                    src_node_id = str(mr.get("source_node_id", "")).strip()
                    tgt_node_id = str(mr.get("target_node_id", "")).strip()
                    if moderator_node_id in seen_node_set or src_node_id in seen_node_set or tgt_node_id in seen_node_set:
                        neighborhood_mods.append(mod)

                neighborhood_inters: list[dict[str, Any]] = []
                for inter in interaction_links:
                    input_node_ids = [str(v or "").strip() for v in (inter.get("input_node_ids", []) or []) if str(v or "").strip()]
                    output_node_id = str(inter.get("output_node_id", "")).strip()
                    if output_node_id in seen_node_set or any(nid in seen_node_set for nid in input_node_ids):
                        neighborhood_inters.append(inter)

                payload = {
                    "node_id": node_id,
                    "nodes": [nodes[nid] for nid in seen_nodes if nid in nodes],
                    "edges": [edges[i] for i in seen_edges if 0 <= i < len(edges)],
                    "moderation_links": neighborhood_mods,
                    "interaction_links": neighborhood_inters,
                }
                return _json(self, payload)

            if path.startswith("/paper/"):
                pid = unquote(path[len("/paper/") :].strip())
                obj = paper_map.get(pid)
                if obj is None:
                    for candidate in paper_map.values():
                        if not isinstance(candidate, dict):
                            continue
                        if str(candidate.get("paper_id", "")).strip() == pid or str(candidate.get("doi", "")).strip() == pid:
                            obj = candidate
                            break
                if obj is None:
                    return _json(self, {"error": "paper_not_found", "paper_id": pid}, status=404)
                payload = dict(obj)
                doi = str(payload.get("doi", "") or payload.get("paper_id", "")).strip()
                if not str(payload.get("article_url", "")).strip() and doi:
                    payload["article_url"] = f"https://sms.onlinelibrary.wiley.com/doi/full/{doi}"
                if "offline_html_path" not in payload:
                    payload["offline_html_path"] = ""
                return _json(self, payload)

            if path.startswith("/variable/"):
                node_id = unquote(path[len("/variable/") :].strip())
                if node_id not in nodes:
                    return _json(self, {"error": "node_not_found", "node_id": node_id}, status=404)
                mentions = node_mentions.get(node_id, [])
                edge_paper_ids = node_to_papers_edge.get(node_id, set())
                moderation_paper_ids = node_to_papers_moderation.get(node_id, set())
                interaction_paper_ids = node_to_papers_interaction.get(node_id, set())
                paper_ids = sorted(edge_paper_ids.union(moderation_paper_ids).union(interaction_paper_ids))
                papers_payload: list[dict[str, Any]] = []
                paper_groups: list[dict[str, Any]] = []
                for pid in paper_ids:
                    p = paper_map_unique.get(pid, {})
                    m: list[dict[str, Any]] = []
                    for x in mentions:
                        if x["paper_id"] != pid:
                            continue
                        src = str(x.get("source", "")).strip()
                        tgt = str(x.get("target", "")).strip()
                        src_name = str(x.get("source_name", "")).strip()
                        tgt_name = str(x.get("target_name", "")).strip()
                        if (src and src == tgt) or (_norm_rel_text(src_name) and _norm_rel_text(src_name) == _norm_rel_text(tgt_name)):
                            continue
                        m.append(x)
                    local_html, online_url = _paper_links(p, pid)
                    variable_name = str(nodes.get(node_id, {}).get("label") or nodes.get(node_id, {}).get("name") or "")
                    raw_defs = list(p.get("variable_definitions", []) or [])
                    concepts = [
                        {
                            "variable": str(d.get("variable", "") or "").strip(),
                            "definition": str(d.get("definition", "") or "").strip(),
                            "evidence_section": str(d.get("definition_evidence_section", "") or "").strip(),
                        }
                        for d in raw_defs
                        if _norm_rel_text(str(d.get("variable", "") or "")) == _norm_rel_text(variable_name)
                        and str(d.get("definition", "") or "").strip()
                    ]
                    operationalization = p.get("operationalization", {})
                    measurement_methods: list[dict[str, Any]] = []
                    if isinstance(operationalization, dict):
                        for v_name, spec in operationalization.items():
                            v_txt = str(v_name or "").strip()
                            if _norm_rel_text(v_txt) != _norm_rel_text(variable_name):
                                continue
                            values: list[str] = []
                            if isinstance(spec, dict):
                                values = [str(x or "").strip() for x in (spec.get("operationalized_as", []) or []) if str(x or "").strip()]
                            elif isinstance(spec, list):
                                values = [str(x or "").strip() for x in spec if str(x or "").strip()]
                            elif isinstance(spec, str):
                                values = [spec.strip()] if spec.strip() else []
                            measurement_methods.append(
                                {
                                    "variable": v_txt,
                                    "operationalized_as": values,
                                }
                            )

                    relation_summaries = [_relation_summary_from_mention(item) for item in m]
                    papers_payload.append(
                        {
                            "paper_id": pid,
                            "doi": str(p.get("doi", "") or pid),
                            "publication_year": p.get("publication_year"),
                            "open_local_html": local_html,
                            "open_online_url": online_url,
                            "mentions": m,
                        }
                    )
                    paper_groups.append(
                        {
                            "paper_id": pid,
                            "doi": str(p.get("doi", "") or pid),
                            "publication_year": p.get("publication_year"),
                            "open_local_html": local_html,
                            "open_online_url": online_url,
                            "concepts": concepts,
                            "measurement_methods": measurement_methods,
                            "relations": relation_summaries,
                        }
                    )
                payload = {
                    "node": nodes[node_id],
                    "paper_count_total": len(paper_ids),
                    "paper_count_edge": len(edge_paper_ids),
                    "paper_count_moderation": len(moderation_paper_ids),
                    "paper_count_interaction": len(interaction_paper_ids),
                    "paper_count": len(paper_ids),
                    "papers": papers_payload,
                    "paper_groups": paper_groups,
                }
                return _json(self, payload)

            self.send_error(404, "Not Found")

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def main() -> None:
    _ENV_UTILS.load_repo_env()
    args = parse_args()
    views_json = _resolve_views_json(args.views_json, args.runs_root)
    _enforce_supply_chain_path(views_json, args.allow_non_supply_chain)
    views = json.loads(views_json.read_text(encoding="utf-8"))
    handler = make_handler(views, args.frontend_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Graph API serving: http://{args.host}:{args.port}/frontend/")
    print(f"Using graph views: {views_json}")
    server.serve_forever()


if __name__ == "__main__":
    main()














