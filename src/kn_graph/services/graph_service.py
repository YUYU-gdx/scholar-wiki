from __future__ import annotations

import importlib.util
import json
import math
import os
from collections import deque
from pathlib import Path
from typing import Any

from kn_graph.config import Settings

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts" / "smj_pipeline"

def _load_module(name: str, relative_path: str):
    module_path = _SCRIPTS_DIR / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    if name not in sys.modules:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


import sys


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


def _parse_year_value(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _extract_theories(paper: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in (
        "theories",
        "theory",
        "theoretical_foundations",
        "theoretical_lens",
        "related_theories",
        "theoretical_background",
    ):
        value = paper.get(key)
        if isinstance(value, list):
            for item in value:
                txt = str(item or "").strip()
                if txt:
                    candidates.append(txt)
        elif isinstance(value, str):
            txt = value.strip()
            if txt:
                candidates.append(txt)
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        norm = _norm_rel_text(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(item)
    return out


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


class GraphService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._current_library: str = ""
        self._views_json: Path | None = None
        self._views: dict[str, Any] | None = None
        self._loaded = False

        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[dict[str, Any]] = []
        self._moderation_links: list[dict[str, Any]] = []
        self._interaction_links: list[dict[str, Any]] = []
        self._edge_index_by_node: dict[str, list[int]] = {}
        self._overview: dict[str, Any] = {}
        self._paper_map: dict[str, dict[str, Any]] = {}
        self._paper_map_unique: dict[str, dict[str, Any]] = {}
        self._meta: dict[str, Any] = {}

        self._node_id_to_name: dict[str, str] = {}
        self._node_mentions: dict[str, list[dict[str, Any]]] = {}
        self._node_to_papers_edge: dict[str, set[str]] = {}
        self._node_to_papers_moderation: dict[str, set[str]] = {}
        self._node_to_papers_interaction: dict[str, set[str]] = {}

        self._definition_entries_by_var: dict[str, list[dict[str, Any]]] = {}
        self._definition_var_names: set[str] = set()
        self._relation_var_names: set[str] = set()
        self._degree_by_node: dict[str, int] = {}
        self._nodes_public_by_id: dict[str, dict[str, Any]] = {}
        self._isolated_nodes: list[dict[str, Any]] = []
        self._meta_public: dict[str, Any] = {}

        self._search_items: list[dict[str, Any]] = []

    def _resolve_views_json(self, library_id: str = "") -> Path | None:
        return self._settings.resolve_graph_views_path(library_id)

    def _ensure_loaded(self, library_id: str = "") -> None:
        if self._loaded and self._current_library == library_id:
            return
        path = self._resolve_views_json(library_id)
        if path is None or not path.exists():
            self._views = {"nodes": {}, "edges": [], "moderation_links": [], "interaction_links": [], "edge_index_by_node": {}, "overview": {"node_ids": [], "edge_indexes": []}, "paper_map": {}, "meta": {"isolated_node_count": 0, "dataset_library_name": ""}}
            self._views_json = path
            self._current_library = library_id
            self._build_indexes()
            self._loaded = True
            return
        try:
            raw = path.read_text(encoding="utf-8")
            self._views = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            self._views = {"nodes": {}, "edges": [], "moderation_links": [], "interaction_links": [], "edge_index_by_node": {}, "overview": {"node_ids": [], "edge_indexes": []}, "paper_map": {}, "meta": {"isolated_node_count": 0, "dataset_library_name": ""}}
        self._views_json = path
        self._current_library = library_id
        self._build_indexes()
        self._loaded = True

    def _build_indexes(self) -> None:
        views = self._views
        self._nodes = views["nodes"]
        self._edges = views["edges"]
        self._moderation_links = views.get("moderation_links", [])
        self._interaction_links = views.get("interaction_links", [])
        self._edge_index_by_node = views["edge_index_by_node"]
        self._overview = views["overview"]
        self._paper_map = views["paper_map"]
        self._meta = views.get("meta", {})

        self._paper_map_unique: dict[str, dict[str, Any]] = {}
        for p in self._paper_map.values():
            if not isinstance(p, dict):
                continue
            pid = str(p.get("paper_id", "")).strip()
            if pid and pid not in self._paper_map_unique:
                self._paper_map_unique[pid] = p

        self._node_id_to_name = {
            nid: str(n.get("label") or n.get("name") or nid)
            for nid, n in self._nodes.items()
        }

        self._node_mentions = {}
        self._node_to_papers_edge = {}
        self._node_to_papers_moderation = {}
        self._node_to_papers_interaction = {}

        for edge in self._edges:
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
                "source_name": str(edge.get("source_name_local", "") or self._node_id_to_name.get(source, source)),
                "target_name": str(edge.get("target_name_local", "") or self._node_id_to_name.get(target, target)),
                "source_name_canonical": self._node_id_to_name.get(source, source),
                "target_name_canonical": self._node_id_to_name.get(target, target),
                "direction": str(edge.get("direction", "") or ""),
                "relation_form": str(edge.get("relation_form", "") or ""),
                "relation_type_std": str(edge.get("relation_type_std", "") or str(edge.get("relation_type", "") or "")),
                "relation_type_raw": str(edge.get("relation_type_raw", "") or str(edge.get("relation_type", "") or "")),
                "evidence_section": str(edge.get("evidence_section", "") or ""),
            }
            mention["mention_kind"] = "edge"
            if source != target:
                self._node_mentions.setdefault(source, []).append(mention)
                self._node_mentions.setdefault(target, []).append(mention)
                self._node_to_papers_edge.setdefault(source, set()).add(pid)
                self._node_to_papers_edge.setdefault(target, set()).add(pid)

        for mod in self._moderation_links:
            pid = str(mod.get("paper_id", "")).strip()
            if not pid:
                continue
            mr = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
            moderator_node_id = str(mod.get("moderator_node_id", "")).strip()
            src_node_id = str(mr.get("source_node_id", "")).strip()
            tgt_node_id = str(mr.get("target_node_id", "")).strip()
            moderator_name = str(mod.get("moderator_var", "") or self._node_id_to_name.get(moderator_node_id, moderator_node_id))
            src_name = str(mr.get("source_var", "") or self._node_id_to_name.get(src_node_id, src_node_id))
            tgt_name = str(mr.get("target_var", "") or self._node_id_to_name.get(tgt_node_id, tgt_node_id))

            mod_mention = {
                "paper_id": pid,
                "doi": str(mod.get("doi", "") or pid),
                "source": src_node_id,
                "target": tgt_node_id,
                "source_name": src_name,
                "target_name": tgt_name,
                "source_name_canonical": self._node_id_to_name.get(src_node_id, src_name),
                "target_name_canonical": self._node_id_to_name.get(tgt_node_id, tgt_name),
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
                self._node_mentions.setdefault(moderator_node_id, []).append(mod_mention)
                self._node_to_papers_moderation.setdefault(moderator_node_id, set()).add(pid)
            if src_node_id and src_node_id != tgt_node_id:
                self._node_mentions.setdefault(src_node_id, []).append(mod_mention)
                self._node_to_papers_moderation.setdefault(src_node_id, set()).add(pid)
            if tgt_node_id and src_node_id != tgt_node_id:
                self._node_mentions.setdefault(tgt_node_id, []).append(mod_mention)
                self._node_to_papers_moderation.setdefault(tgt_node_id, set()).add(pid)

        for inter in self._interaction_links:
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
                "source_name": " x ".join(str(v or "") for v in (inter.get("inputs", []) or [])),
                "target_name": str(inter.get("output", "") or self._node_id_to_name.get(output_id, output_id)),
                "source_name_canonical": " x ".join(self._node_id_to_name.get(nid, nid) for nid in input_ids),
                "target_name_canonical": self._node_id_to_name.get(output_id, output_id),
                "direction": str(inter.get("effect", "") or ""),
                "relation_form": "interaction",
                "relation_type_std": "interaction",
                "relation_type_raw": str(inter.get("interaction_type", "") or "interaction"),
                "evidence_section": str(inter.get("evidence_section", "") or ""),
                "mention_kind": "interaction",
            }
            for nid in input_ids:
                self._node_mentions.setdefault(nid, []).append(interaction_mention)
                self._node_to_papers_interaction.setdefault(nid, set()).add(pid)
            if output_id:
                self._node_mentions.setdefault(output_id, []).append(interaction_mention)
                self._node_to_papers_interaction.setdefault(output_id, set()).add(pid)

        self._relation_var_names: set[str] = set()
        for edge in self._edges:
            source_id = str(edge.get("source", "") or "").strip()
            target_id = str(edge.get("target", "") or "").strip()
            for nid in (source_id, target_id):
                if nid and nid in self._node_id_to_name:
                    norm = _norm_rel_text(self._node_id_to_name.get(nid, ""))
                    if norm:
                        self._relation_var_names.add(norm)
            for key in ("source_name_local", "source_name", "source"):
                txt = str(edge.get(key, "") or "").strip()
                norm = _norm_rel_text(txt)
                if norm:
                    self._relation_var_names.add(norm)
                    break
            for key in ("target_name_local", "target_name", "target"):
                txt = str(edge.get(key, "") or "").strip()
                norm = _norm_rel_text(txt)
                if norm:
                    self._relation_var_names.add(norm)
                    break
        for mod in self._moderation_links:
            moderator = str(mod.get("moderator_var", "") or "").strip()
            relation = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
            src = str(relation.get("source_var", "") or "").strip()
            tgt = str(relation.get("target_var", "") or "").strip()
            for txt in (moderator, src, tgt):
                norm = _norm_rel_text(txt)
                if norm:
                    self._relation_var_names.add(norm)
        for inter in self._interaction_links:
            output = str(inter.get("output", "") or "").strip()
            norm_output = _norm_rel_text(output)
            if norm_output:
                self._relation_var_names.add(norm_output)
            for inp in inter.get("inputs", []) or []:
                norm = _norm_rel_text(str(inp or "").strip())
                if norm:
                    self._relation_var_names.add(norm)

        self._definition_entries_by_var = {}
        self._definition_var_names = set()
        for pid, paper in self._paper_map_unique.items():
            publication_year = _parse_year_value(paper.get("publication_year"))
            definitions = paper.get("variable_definitions", []) or []
            if not isinstance(definitions, list):
                continue
            theories = _extract_theories(paper)
            for item in definitions:
                if not isinstance(item, dict):
                    continue
                variable = str(item.get("variable", "") or "").strip()
                definition = str(item.get("definition", "") or "").strip()
                evidence = str(item.get("definition_evidence_section", "") or "").strip()
                norm = _norm_rel_text(variable)
                if not norm:
                    continue
                self._definition_var_names.add(norm)
                self._definition_entries_by_var.setdefault(norm, []).append(
                    {
                        "paper_id": pid,
                        "publication_year": publication_year,
                        "variable": variable,
                        "definition": definition,
                        "evidence_section": evidence,
                        "theories": theories,
                    }
                )

        self._degree_by_node = {nid: 0 for nid in self._nodes}
        for edge in self._edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if source in self._degree_by_node:
                self._degree_by_node[source] += 1
            if target in self._degree_by_node:
                self._degree_by_node[target] += 1

        self._nodes_public_by_id = {}
        self._isolated_nodes = []
        for nid, node in self._nodes.items():
            payload = dict(node)
            node_type = str(node.get("type", "")).strip()
            norm_label = _norm_rel_text(str(node.get("label") or node.get("name") or nid))
            in_rel = bool(norm_label and norm_label in self._relation_var_names)
            in_defs = bool(norm_label and norm_label in self._definition_var_names)
            is_validated = bool(in_rel or in_defs)
            degree = int(self._degree_by_node.get(nid, 0))
            payload["validated_variable"] = is_validated if node_type == "variable" else True
            payload["relation_degree"] = degree
            payload["is_isolated"] = bool(node_type == "variable" and degree == 0)
            payload["library_name"] = "供应链"

            if norm_label and norm_label in self._definition_entries_by_var:
                entries = self._definition_entries_by_var.get(norm_label, [])
                concept_entry = sorted(
                    entries,
                    key=lambda x: (
                        int(x.get("publication_year")) if isinstance(x.get("publication_year"), int) else -1,
                        str(x.get("paper_id", "")),
                    ),
                    reverse=True,
                )[0]
                payload["latest_concept"] = str(concept_entry.get("definition", "") or "")
                payload["latest_concept_source"] = {
                    "paper_id": str(concept_entry.get("paper_id", "") or ""),
                    "publication_year": concept_entry.get("publication_year"),
                    "evidence_section": str(concept_entry.get("evidence_section", "") or ""),
                }
                payload["latest_theories"] = list(concept_entry.get("theories", []) or [])
            else:
                payload["latest_concept"] = ""
                payload["latest_concept_source"] = {}
                payload["latest_theories"] = []

            if node_type == "variable" and degree == 0:
                reason = "unvalidated" if not is_validated else ("definition_only" if in_defs and not in_rel else ("relation_only" if in_rel and not in_defs else "no_relation_extracted"))
                self._isolated_nodes.append(
                    {
                        "node_id": nid,
                        "label": str(node.get("label") or node.get("name") or nid),
                        "reason": reason,
                    }
                )
            self._nodes_public_by_id[nid] = payload

        self._meta_public = dict(self._meta)
        self._meta_public["isolated_node_count"] = len(self._isolated_nodes)
        self._meta_public["dataset_library_name"] = "供应链"

        self._search_items = []
        for nid, node in self._nodes.items():
            if str(node.get("type", "")) != "variable":
                continue
            mentions = self._node_mentions.get(nid, [])
            predecessors = sorted({m["source_name"] for m in mentions if m["target"] == nid and m["source"] != nid})[:8]
            successors = sorted({m["target_name"] for m in mentions if m["source"] == nid and m["target"] != nid})[:8]
            paper_ids = sorted(
                self._node_to_papers_edge.get(nid, set())
                .union(self._node_to_papers_moderation.get(nid, set()))
                .union(self._node_to_papers_interaction.get(nid, set()))
            )
            card = {
                "kind": "variable",
                "id": nid,
                "title": str(node.get("label") or node.get("name") or nid),
                "predecessors": predecessors,
                "successors": successors,
                "papers": paper_ids[:20],
            }
            text_blob = " ".join([card["title"], " ".join(predecessors), " ".join(successors), " ".join(card["papers"])])
            self._search_items.append({
                "mode": "variable",
                "card": card,
                "tokens": set(_tokenize(text_blob)),
                "embedding": _hash_embedding(text_blob),
            })

        for pid, paper in self._paper_map_unique.items():
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
            self._search_items.append({
                "mode": "paper",
                "card": card,
                "tokens": set(_tokenize(text_blob)),
                "embedding": _hash_embedding(text_blob),
            })

    def get_overview(self, library_id: str = "") -> dict[str, Any]:
        self._ensure_loaded(library_id)
        return {
            "meta": self._meta_public,
            "nodes": [self._nodes_public_by_id[nid] for nid in self._overview["node_ids"] if nid in self._nodes_public_by_id],
            "edges": [self._edges[i] for i in self._overview["edge_indexes"] if 0 <= i < len(self._edges)],
            "moderation_links": self._moderation_links,
            "interaction_links": self._interaction_links,
            "isolated_nodes": self._isolated_nodes,
        }

    def get_full(self, library_id: str = "") -> dict[str, Any]:
        self._ensure_loaded(library_id)
        return {
            "meta": self._meta_public,
            "nodes": list(self._nodes_public_by_id.values()),
            "edges": self._edges,
            "moderation_links": self._moderation_links,
            "interaction_links": self._interaction_links,
            "paper_map": self._paper_map_unique,
            "isolated_nodes": self._isolated_nodes,
        }

    def search(
        self,
        query: str = "",
        mode: str = "variable",
        limit: int = 20,
        keyword_weight: float = 0.5,
        vector_weight: float = 0.5,
        vector_backend: str = "hash",
        library_id: str = "",
    ) -> dict[str, Any]:
        self._ensure_loaded(library_id)
        query_text = str(query or "").strip().lower()
        if not query_text:
            return {"results": [], "search_meta": {"vector_backend_requested": vector_backend, "vector_backend_used": "hash"}}
        q_tokens = set(_tokenize(query_text))
        q_emb = _hash_embedding(query_text)
        backend_used = "hash"
        backend_note = ""
        if vector_backend == "embedding":
            if os.getenv("GRAPH_EMBEDDING_MODEL", "").strip():
                backend_note = "embedding backend requested but unavailable; fallback to hash."
            else:
                backend_note = "embedding model not configured; fallback to hash."
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in self._search_items:
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
        return {
            "results": [p for _, p in ranked[:limit]],
            "search_meta": {
                "vector_backend_requested": vector_backend,
                "vector_backend_used": backend_used,
                "note": backend_note,
            },
        }

    def get_neighborhood(
        self,
        node_id: str,
        hops: int = 1,
        limit_nodes: int = 350,
        limit_edges: int = 900,
        library_id: str = "",
    ) -> dict[str, Any] | None:
        self._ensure_loaded(library_id)
        if node_id not in self._nodes:
            return None

        seen_nodes = {node_id}
        seen_edges: list[int] = []
        qd: deque[tuple[str, int]] = deque([(node_id, 0)])

        while qd and len(seen_nodes) < limit_nodes and len(seen_edges) < limit_edges:
            cur, depth = qd.popleft()
            if depth >= hops:
                continue
            for ei in self._edge_index_by_node.get(cur, []):
                if ei not in seen_edges:
                    seen_edges.append(ei)
                e = self._edges[ei]
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
        for mod in self._moderation_links:
            mr = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
            moderator_node_id = str(mod.get("moderator_node_id", "")).strip()
            src_node_id = str(mr.get("source_node_id", "")).strip()
            tgt_node_id = str(mr.get("target_node_id", "")).strip()
            if moderator_node_id in seen_node_set or src_node_id in seen_node_set or tgt_node_id in seen_node_set:
                neighborhood_mods.append(mod)

        neighborhood_inters: list[dict[str, Any]] = []
        for inter in self._interaction_links:
            input_node_ids = [str(v or "").strip() for v in (inter.get("input_node_ids", []) or []) if str(v or "").strip()]
            output_node_id = str(inter.get("output_node_id", "")).strip()
            if output_node_id in seen_node_set or any(nid in seen_node_set for nid in input_node_ids):
                neighborhood_inters.append(inter)

        return {
            "node_id": node_id,
            "nodes": [self._nodes_public_by_id[nid] for nid in seen_nodes if nid in self._nodes_public_by_id],
            "edges": [self._edges[i] for i in seen_edges if 0 <= i < len(self._edges)],
            "moderation_links": neighborhood_mods,
            "interaction_links": neighborhood_inters,
        }

    def get_paper(self, paper_id_or_doi: str, library_id: str = "") -> dict[str, Any] | None:
        self._ensure_loaded(library_id)
        pid = str(paper_id_or_doi or "").strip()
        if not pid:
            return None
        obj = self._paper_map.get(pid)
        if obj is None:
            for candidate in self._paper_map.values():
                if not isinstance(candidate, dict):
                    continue
                if str(candidate.get("paper_id", "")).strip() == pid or str(candidate.get("doi", "")).strip() == pid:
                    obj = candidate
                    break
        if obj is None:
            return None
        payload = dict(obj)
        doi = str(payload.get("doi", "") or payload.get("paper_id", "")).strip()
        if not str(payload.get("article_url", "")).strip() and doi:
            payload["article_url"] = f"https://sms.onlinelibrary.wiley.com/doi/full/{doi}"
        if "offline_html_path" not in payload:
            payload["offline_html_path"] = ""
        return payload

    def reload(self, library_id: str = "") -> dict[str, Any]:
        self._loaded = False
        self._current_library = ""
        try:
            self._ensure_loaded(library_id)
            return {"status": "ok", "library_id": library_id, "node_count": len(self._nodes)}
        except Exception as exc:
            return {"status": "error", "library_id": library_id, "error": str(exc)}

    def get_variable(self, node_id: str, library_id: str = "") -> dict[str, Any] | None:
        self._ensure_loaded(library_id)
        nid = str(node_id or "").strip()
        if nid not in self._nodes:
            return None
        mentions = self._node_mentions.get(nid, [])
        edge_paper_ids = self._node_to_papers_edge.get(nid, set())
        moderation_paper_ids = self._node_to_papers_moderation.get(nid, set())
        interaction_paper_ids = self._node_to_papers_interaction.get(nid, set())
        paper_ids = sorted(edge_paper_ids.union(moderation_paper_ids).union(interaction_paper_ids))

        papers_payload: list[dict[str, Any]] = []
        paper_groups: list[dict[str, Any]] = []
        for pid in paper_ids:
            p = self._paper_map_unique.get(pid, {})
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
            variable_name = str(self._nodes.get(nid, {}).get("label") or self._nodes.get(nid, {}).get("name") or "")
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

        return {
            "node": self._nodes_public_by_id.get(nid, self._nodes[nid]),
            "paper_count_total": len(paper_ids),
            "paper_count_edge": len(edge_paper_ids),
            "paper_count_moderation": len(moderation_paper_ids),
            "paper_count_interaction": len(interaction_paper_ids),
            "paper_count": len(paper_ids),
            "papers": papers_payload,
            "paper_groups": paper_groups,
        }
