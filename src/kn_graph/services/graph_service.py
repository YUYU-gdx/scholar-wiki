from __future__ import annotations

import json
import math
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

from kn_graph.config import Settings


def _resolve_storage_uri(uri: str) -> str:
    """Strip legacy storage:// prefix if present, returning a clean filesystem path."""
    text = str(uri or "").strip()
    if text.startswith("storage://"):
        return text[len("storage://"):]
    return text




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


def _safe_parse_authors_json(raw: object) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(str(raw or "[]"))
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
    except Exception:
        pass
    return []


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
    theory_name = str(
        m.get("theory_name", "")
        or m.get("hypothesis_label", "")
        or m.get("relation_type_std", "")
        or m.get("relation_type_raw", "")
        or ""
    ).strip()
    kind = str(m.get("mention_kind", "edge") or "edge")
    if kind == "interaction":
        return {
            "kind": "interaction",
            "title": f"{str(m.get('source_name', '') or '').strip()} -> {str(m.get('target_name', '') or '').strip()}",
            "direction": str(m.get("effect_form", "") or "").strip(),
            "relation_form": "interaction",
            "relation_type": str(m.get("relation_type_std", "interaction") or "interaction"),
            "evidence_section": str(m.get("evidence_text", "") or "").strip(),
            "theory_name": theory_name,
        }
    if kind == "moderation":
        moderator = str(m.get("moderator_name", "") or "").strip()
        src = str(m.get("source_name", "") or "").strip()
        tgt = str(m.get("target_name", "") or "").strip()
        return {
            "kind": "moderation",
            "title": f"{moderator} 调节 {src} -> {tgt}",
            "direction": str(m.get("effect_form", "") or "").strip(),
            "relation_form": str(m.get("effect_form", "linear") or "linear"),
            "relation_type": "moderation",
            "evidence_section": str(m.get("evidence_text", "") or "").strip(),
            "theory_name": theory_name,
        }
    src = str(m.get("source_name", "") or "").strip()
    tgt = str(m.get("target_name", "") or "").strip()
    return {
        "kind": "direct_effect",
        "title": f"{src} -> {tgt}",
        "direction": str(m.get("effect_form", "") or "").strip(),
        "relation_form": str(m.get("effect_form", "") or "").strip(),
        "relation_type": str(m.get("relation_type_std", "") or "").strip(),
        "evidence_section": str(m.get("evidence_text", "") or "").strip(),
        "theory_name": theory_name,
    }


class GraphService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._current_library: str = ""
        self._views_json: Path | None = None
        self._views: dict[str, Any] | None = None
        self._loaded = False
        self._views_mtime: float = 0

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
        self._paper_meta_by_id: dict[str, dict[str, Any]] = {}

    def _resolve_views_json(self, library_id: str = "") -> Path | None:
        return self._settings.resolve_graph_views_path(library_id)

    @staticmethod
    def _normalize_edge(row: dict[str, Any], paper_key_by_pid: dict[str, str] | None = None) -> dict[str, Any]:
        out = dict(row or {})
        source = str(out.get("source", "") or "").strip()
        target = str(out.get("target", "") or "").strip()
        out["source"] = source
        out["target"] = target

        rel_type_std = str(out.get("relation_type_std", "") or out.get("relation_type", "") or "").strip()
        effect_form = str(out.get("effect_form", "") or "").strip()
        out["relation_type_std"] = rel_type_std
        out["relation_type"] = str(out.get("relation_type", "") or rel_type_std).strip()
        out["relation_type_raw"] = str(out.get("relation_type_raw", "") or out.get("relation_type", "") or "").strip()
        out["effect_form"] = effect_form
        out["direction"] = effect_form
        out["relation_form"] = effect_form
        out["evidence_section"] = str(out.get("evidence_text", "") or "").strip()
        out["evidence_snippet"] = str(out.get("evidence_text", "") or "").strip()
        out["evidence_anchor"] = str(out.get("evidence_anchor", "") or "").strip()
        out["verification"] = str(out.get("verification", "") or "").strip()
        out["hypothesis_label"] = str(out.get("theory_name", "") or "").strip()
        out["display_effect_class"] = str(out.get("display_effect_class", "") or effect_form).strip()

        pid_raw = str(out.get("paper_id_raw", "") or out.get("paper_id", "") or "").strip()
        out["paper_id_raw"] = pid_raw
        if pid_raw and paper_key_by_pid:
            out["paper_id"] = paper_key_by_pid.get(pid_raw, pid_raw)
        else:
            out["paper_id"] = pid_raw
        out["doi"] = str(out.get("doi", "") or "").strip()
        return out

    @staticmethod
    def _normalize_moderation_link(row: dict[str, Any], paper_key_by_pid: dict[str, str] | None = None) -> dict[str, Any]:
        out = dict(row or {})
        mod_rel = out.get("moderated_relation") if isinstance(out.get("moderated_relation"), dict) else {}
        source_node_id = str(mod_rel.get("source_node_id", "") or mod_rel.get("source", "") or "").strip()
        target_node_id = str(mod_rel.get("target_node_id", "") or mod_rel.get("target", "") or "").strip()
        source_var = str(mod_rel.get("source_var", "") or "").strip()
        target_var = str(mod_rel.get("target_var", "") or "").strip()
        out["moderated_relation"] = {
            "source": source_node_id,
            "target": target_node_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "source_var": source_var,
            "target_var": target_var,
        }
        out["moderator_node_id"] = str(out.get("moderator_node_id", "") or "").strip()
        out["moderator_var"] = str(out.get("moderator_var", "") or "").strip()
        out["direction"] = str(out.get("effect_form", "") or "").strip()
        out["verification"] = str(out.get("verification", "") or "").strip()
        out["hypothesis_label"] = str(out.get("theory_name", "") or "").strip()
        out["evidence_section"] = str(out.get("evidence_text", "") or "").strip()
        out["evidence_snippet"] = str(out.get("evidence_text", "") or "").strip()
        out["evidence_anchor"] = str(out.get("evidence_anchor", "") or "").strip()

        pid_raw = str(out.get("paper_id_raw", "") or out.get("paper_id", "") or "").strip()
        out["paper_id_raw"] = pid_raw
        if pid_raw and paper_key_by_pid:
            out["paper_id"] = paper_key_by_pid.get(pid_raw, pid_raw)
        else:
            out["paper_id"] = pid_raw
        out["doi"] = str(out.get("doi", "") or "").strip()
        return out

    @staticmethod
    def _normalize_interaction_link(row: dict[str, Any], paper_key_by_pid: dict[str, str] | None = None) -> dict[str, Any]:
        out = dict(row or {})
        input_node_ids = [str(v or "").strip() for v in (out.get("input_node_ids", []) or []) if str(v or "").strip()]
        out["input_node_ids"] = input_node_ids
        out["inputs"] = [str(v or "").strip() for v in (out.get("inputs", []) or []) if str(v or "").strip()]
        out["output_node_id"] = str(out.get("output_node_id", "") or "").strip()
        out["output"] = str(out.get("output", "") or "").strip()
        out["interaction_type"] = str(out.get("theory_name", "") or "").strip()
        out["effect"] = str(out.get("effect_form", "") or "").strip()
        out["verification"] = str(out.get("verification", "") or "").strip()
        out["hypothesis_label"] = str(out.get("theory_name", "") or "").strip()
        out["evidence_section"] = str(out.get("evidence_text", "") or "").strip()
        out["evidence_snippet"] = str(out.get("evidence_text", "") or "").strip()
        out["description"] = str(out.get("description", "") or "").strip()
        out["moderator"] = str(out.get("moderator", "") or "").strip()
        out["moderator_node_id"] = str(out.get("moderator_node_id", "") or "").strip()

        pid_raw = str(out.get("paper_id_raw", "") or out.get("paper_id", "") or "").strip()
        out["paper_id_raw"] = pid_raw
        if pid_raw and paper_key_by_pid:
            out["paper_id"] = paper_key_by_pid.get(pid_raw, pid_raw)
        else:
            out["paper_id"] = pid_raw
        out["doi"] = str(out.get("doi", "") or "").strip()
        return out

    def _ensure_loaded(self, library_id: str = "") -> None:
        path = self._resolve_views_json(library_id)
        # Reload if the file has been modified since last load (e.g. by a pipeline job)
        if self._loaded and self._current_library == library_id:
            try:
                if path and path.exists() and path.stat().st_mtime <= self._views_mtime:
                    return
            except OSError:
                return
        if path is None or not path.exists():
            self._views = {"nodes": {}, "edges": [], "moderation_links": [], "interaction_links": [], "edge_index_by_node": {}, "overview": {"node_ids": [], "edge_indexes": []}, "paper_map": {}, "meta": {"isolated_node_count": 0, "dataset_library_name": ""}}
            self._views_json = path
            self._current_library = library_id
            self._build_indexes()
            self._loaded = True
            self._views_mtime = time.time()
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
        self._views_mtime = time.time()

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
                "direction": str(edge.get("effect_form", "") or edge.get("direction", "") or edge.get("relation_form", "") or ""),
                "relation_form": str(edge.get("effect_form", "") or edge.get("relation_form", "") or ""),
                "relation_type_std": str(edge.get("relation_type_std", "") or str(edge.get("relation_type", "") or "")),
                "relation_type_raw": str(edge.get("relation_type_raw", "") or str(edge.get("relation_type", "") or "")),
                "evidence_text": str(edge.get("evidence_text", "") or edge.get("evidence_snippet", "") or ""),
                "evidence_section": str(edge.get("evidence_text", "") or edge.get("evidence_snippet", "") or ""),
                "theory_name": str(edge.get("theory_name", "") or edge.get("hypothesis_label", "") or edge.get("relation_type_std", "") or edge.get("relation_type", "") or ""),
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
            src_node_id = str(mr.get("source_node_id", "") or mr.get("source", "")).strip()
            tgt_node_id = str(mr.get("target_node_id", "") or mr.get("target", "")).strip()
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
                "evidence_section": str(mod.get("evidence_text", "") or ""),
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
                "direction": str(inter.get("effect_form", "") or ""),
                "relation_form": "interaction",
                "relation_type_std": "interaction",
                "relation_type_raw": str(inter.get("theory_name", "") or "interaction"),
                "evidence_section": str(inter.get("evidence_text", "") or ""),
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
                variable = str(item.get("variable_name", "") or item.get("variable", "") or "").strip()
                definition = str(item.get("definition", "") or "").strip()
                evidence = str(item.get("measurement", "") or "").strip()
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
                    "evidence_section": str(concept_entry.get("evidence_text", "") or ""),
                }
                payload["latest_theories"] = list(concept_entry.get("theories", []) or [])
            else:
                # Fall back to extracted definition from paper if no concept entry
                extracted_def = str(node.get("definition", "") or "").strip()
                payload["latest_concept"] = extracted_def
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
                "library_id": self._current_library,
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
            rels = list(paper.get("direct_effects", []) or [])
            inters = list(paper.get("interactions", []) or [])
            rel_snippets: list[str] = []
            for r in rels[:20]:
                src = str(r.get("source", "") or r.get("from", "")).strip()
                tgt = str(r.get("target", "") or r.get("to", "")).strip()
                tag = str(r.get("effect_form", "") or r.get("effect_form", "") or r.get("relation_type", "")).strip()
                rel_snippets.append(f"{src}->{tgt} {tag}".strip())
            for it in inters[:10]:
                inputs = [str(v or "").strip() for v in (it.get("inputs", []) or []) if str(v or "").strip()]
                output = str(it.get("output", "") or "").strip()
                if len(inputs) >= 2 and output:
                    rel_snippets.append(f"{' x '.join(inputs)}->{output} interaction")
            card = {
                "kind": "paper",
                "id": pid,
                "library_id": self._current_library,
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
        self._load_sqlite_paper_meta()

    def _load_sqlite_paper_meta(self) -> None:
        """Load paper metadata from SQLite (single source of truth)."""
        self._paper_meta_by_id: dict[str, dict[str, Any]] = {}
        lib = str(self._current_library or "").strip()
        if not lib:
            return
        db_path = self._settings.workspaces_dir / lib / "kn_gragh.db"
        if not db_path.exists():
            return
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT paper_id, title, doi, authors_json, journal, publication_date, publication_year, "
            "source_pdf_path, source_md_path, source_html_path, offline_html_path, article_url FROM papers"
        )
        for r in cur.fetchall():
            meta = dict(r)
            pid = str(meta.get("paper_id", "") or "").strip()
            if pid:
                self._paper_meta_by_id[pid] = meta
        conn.close()

    def get_overview(self, library_id: str = "") -> dict[str, Any]:
        self._ensure_loaded(library_id)
        edges_normalized = [self._normalize_edge(self._edges[i]) for i in self._overview["edge_indexes"] if 0 <= i < len(self._edges)]
        moderation_normalized = [self._normalize_moderation_link(m) for m in self._moderation_links]
        interaction_normalized = [self._normalize_interaction_link(it) for it in self._interaction_links]
        return {
            "meta": self._meta_public,
            "nodes": [self._nodes_public_by_id[nid] for nid in self._overview["node_ids"] if nid in self._nodes_public_by_id],
            "edges": edges_normalized,
            "moderation_links": moderation_normalized,
            "interaction_links": interaction_normalized,
            "isolated_nodes": self._isolated_nodes,
        }

    def get_full(self, library_id: str = "") -> dict[str, Any]:
        self._ensure_loaded(library_id)

        # Paper map: single source from SQLite
        paper_map_with_display: dict[str, dict[str, Any]] = {}
        for pid, meta in self._paper_meta_by_id.items():
            paper_map_with_display[pid] = {
                "library_id": library_id,
                "paper_id": pid,
                "paper_key": pid,
                "source_pdf_path": str(meta.get("source_pdf_path", "") or ""),
                "source_md_path": str(meta.get("source_md_path", "") or ""),
                "source_html_path": str(meta.get("source_html_path", "") or ""),
                "offline_html_path": str(meta.get("offline_html_path", "") or ""),
                "title": str(meta.get("title", "") or "").strip() or pid,
                "display_title": str(meta.get("title", "") or "").strip() or pid,
                "doi": str(meta.get("doi", "") or pid),
                "article_url": str(meta.get("article_url", "") or ""),
                "authors_json": _safe_parse_authors_json(meta.get("authors_json", "[]")),
                "journal": str(meta.get("journal", "") or ""),
                "publication_date": str(meta.get("publication_date", "") or ""),
                "publication_year": _parse_year_value(meta.get("publication_year")),
            }

        # Map graph_views paper_ids → SQLite paper_keys for node/edge normalization
        gv_pid_to_pkey: dict[str, str] = {}
        for gv_pid, gv_paper in self._paper_map_unique.items():
            pkey = str(gv_paper.get("paper_key", "") or gv_paper.get("paper_id", "") or "").strip()
            if pkey and pkey in self._paper_meta_by_id:
                gv_pid_to_pkey[gv_pid] = pkey

        # Normalize nodes: replace graph_views paper_id with workspace paper_key
        normalized_nodes: list[dict[str, Any]] = []
        for n in self._nodes_public_by_id.values():
            node_copy = dict(n)
            src = node_copy.get("latest_concept_source")
            if isinstance(src, dict) and src.get("paper_id"):
                src_copy = dict(src)
                gv_pid = str(src_copy.get("paper_id", "") or "").strip()
                if gv_pid in gv_pid_to_pkey:
                    src_copy["paper_id_raw"] = gv_pid
                    src_copy["paper_id"] = gv_pid_to_pkey[gv_pid]
                node_copy["latest_concept_source"] = src_copy
            node_copy["library_id"] = library_id
            normalized_nodes.append(node_copy)

        edges_mapped = [self._normalize_edge(edge) for edge in self._edges]
        moderation_mapped = [self._normalize_moderation_link(mod) for mod in self._moderation_links]
        interaction_mapped = [self._normalize_interaction_link(inter) for inter in self._interaction_links]

        # Normalize edges: replace graph_views paper_id with workspace paper_key
        edges_normalized: list[dict[str, Any]] = []
        for e in edges_mapped:
            edge_copy = dict(e)
            gv_pid = str(edge_copy.get("paper_id", "")).strip()
            if gv_pid in gv_pid_to_pkey:
                edge_copy["paper_id_raw"] = gv_pid
                edge_copy["paper_id"] = gv_pid_to_pkey[gv_pid]
            edges_normalized.append(edge_copy)

        return {
            "meta": {**self._meta_public, "library_id": library_id},
            "nodes": normalized_nodes,
            "edges": edges_normalized,
            "moderation_links": moderation_mapped,
            "interaction_links": interaction_mapped,
            "paper_map": paper_map_with_display,
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
            if self._settings.graph_embedding_model.strip():
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
            src_node_id = str(mr.get("source_node_id", "") or mr.get("source", "")).strip()
            tgt_node_id = str(mr.get("target_node_id", "") or mr.get("target", "")).strip()
            if moderator_node_id in seen_node_set or src_node_id in seen_node_set or tgt_node_id in seen_node_set:
                neighborhood_mods.append(self._normalize_moderation_link(mod))

        neighborhood_inters: list[dict[str, Any]] = []
        for inter in self._interaction_links:
            input_node_ids = [str(v or "").strip() for v in (inter.get("input_node_ids", []) or []) if str(v or "").strip()]
            output_node_id = str(inter.get("output_node_id", "")).strip()
            if output_node_id in seen_node_set or any(nid in seen_node_set for nid in input_node_ids):
                neighborhood_inters.append(self._normalize_interaction_link(inter))

        return {
            "node_id": node_id,
            "nodes": [self._nodes_public_by_id[nid] for nid in seen_nodes if nid in self._nodes_public_by_id],
            "edges": [self._normalize_edge(self._edges[i]) for i in seen_edges if 0 <= i < len(self._edges)],
            "moderation_links": neighborhood_mods,
            "interaction_links": neighborhood_inters,
        }

    def get_paper(self, paper_id_or_doi: str, library_id: str = "") -> dict[str, Any] | None:
        self._ensure_loaded(library_id)
        pid = str(paper_id_or_doi or "").strip()
        if not pid:
            return None
        # Look up in memory cache first; fall back to direct DB read
        sqlite_meta = self._paper_meta_by_id.get(pid, {})
        if not sqlite_meta:
            db_path = self._settings.workspaces_dir / library_id / "kn_gragh.db"
            if db_path.exists():
                import sqlite3
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT paper_id, title, doi, source_pdf_path, source_md_path, source_html_path, offline_html_path, article_url FROM papers WHERE paper_id = ?", (pid,))
                row = cur.fetchone()
                conn.close()
                if row:
                    sqlite_meta = dict(row)
        if not sqlite_meta:
            return None
        # Build from SQLite metadata; graph_views extraction fields can be
        # layered in later when the caller needs them.
        return {
            "paper_id": pid,
            "paper_key": pid,
            "library_id": library_id,
            "title": str(sqlite_meta.get("title", "") or "").strip() or pid,
            "display_title": str(sqlite_meta.get("title", "") or "").strip() or pid,
            "doi": str(sqlite_meta.get("doi", "") or pid),
            "source_pdf_path": str(sqlite_meta.get("source_pdf_path", "") or ""),
            "source_md_path": str(sqlite_meta.get("source_md_path", "") or ""),
            "source_html_path": str(sqlite_meta.get("source_html_path", "") or ""),
            "offline_html_path": str(sqlite_meta.get("offline_html_path", "") or ""),
            "article_url": str(sqlite_meta.get("article_url", "") or ""),
        }

    def get_paper_files(self, paper_id_or_doi: str, library_id: str = "") -> dict[str, Any] | None:
        """Return available readable files for a paper."""
        paper = self.get_paper(paper_id_or_doi, library_id=library_id)
        if paper is None:
            return None

        source_pdf = _resolve_storage_uri(paper.get("source_pdf_path", "") or "")
        source_md = _resolve_storage_uri(paper.get("source_md_path", "") or "")
        offline_html = _resolve_storage_uri(paper.get("offline_html_path", "") or "")

        files: dict[str, dict[str, Any]] = {}
        default_view = "none"

        if source_md:
            try:
                p = Path(source_md)
                if p.exists() and p.is_file():
                    files["markdown"] = {
                        "path": str(p),
                        "name": p.name,
                        "size_bytes": p.stat().st_size,
                    }
                    if default_view == "none":
                        default_view = "markdown"
                elif p.exists() and p.is_dir():
                    for cand_name in ("full.md", "merged.md", "output.md"):
                        cand = p / cand_name
                        if cand.exists():
                            files["markdown"] = {
                                "path": str(cand),
                                "name": cand.name,
                                "size_bytes": cand.stat().st_size,
                            }
                            if default_view == "none":
                                default_view = "markdown"
                            break
            except OSError:
                pass

        if offline_html:
            try:
                p = Path(offline_html)
                if p.exists():
                    files["html"] = {
                        "path": offline_html,
                        "name": p.name,
                        "size_bytes": p.stat().st_size,
                    }
                    if default_view == "none":
                        default_view = "html"
            except OSError:
                pass

        if source_pdf:
            try:
                p = Path(source_pdf)
                if p.exists():
                    files["pdf"] = {
                        "path": source_pdf,
                        "name": p.name,
                        "size_bytes": p.stat().st_size,
                    }
                    if default_view == "none":
                        default_view = "pdf"
            except OSError:
                pass

        # Resolve content_list_v2.json for PDF↔markdown position mapping
        content_list_v2_path = ""
        mineru_dir = None
        if source_md:
            md_path = Path(source_md)
            candidate_dir = md_path.parent if md_path.is_file() else md_path
            if candidate_dir.exists():
                mineru_dir = candidate_dir
        if mineru_dir is None and source_pdf:
            pdf_path = Path(source_pdf)
            if pdf_path.parent.exists():
                mineru_dir = pdf_path.parent
        if mineru_dir is not None:
            try:
                matches = list(mineru_dir.glob("*_content_list_v2.json"))
                if matches:
                    content_list_v2_path = str(matches[0])
            except OSError:
                pass

        return {
            "paper_id": paper.get("paper_id", paper_id_or_doi),
            "library_id": paper.get("library_id", library_id),
            "files": files,
            "default_view": default_view,
            "content_list_v2_path": content_list_v2_path,
        }

    def delete_paper(self, paper_id_or_doi: str, library_id: str = "") -> dict[str, Any] | None:
        """Delete a paper: SQLite, disk files, then rebuild graph_views."""
        self._ensure_loaded(library_id)
        paper = self.get_paper(paper_id_or_doi, library_id=library_id)
        if paper is None:
            return None
        pid = str(paper.get("paper_id", "") or "").strip()
        pkey = str(paper.get("paper_key", "") or pid).strip()
        deleted = {"paper_id": pid, "paper_key": pkey, "library_id": library_id, "deleted": []}

        # 1. SQLite: delete paper + related rows
        db_path = self._settings.workspaces_dir / library_id / "kn_gragh.db"
        if db_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            # Delete interaction_inputs first (FK to interactions)
            cur.execute("DELETE FROM interaction_inputs WHERE interaction_id IN (SELECT id FROM interactions WHERE paper_id = ?)", (pid,))
            for table in ("paper_domains", "variable_aliases", "variable_definitions",
                          "direct_effects", "moderations", "interactions"):
                cur.execute(f"DELETE FROM {table} WHERE paper_id = ?", (pid,))
            cur.execute("DELETE FROM papers WHERE paper_id = ?", (pid,))
            conn.commit()
            conn.close()
            deleted["deleted"].append("sqlite")

        # 2. Disk: remove paper directory
        import shutil
        ws = self._settings.workspaces_dir / library_id
        paper_dir = ws / "corpus" / "papers" / pkey
        if paper_dir.exists():
            shutil.rmtree(paper_dir, ignore_errors=True)
            deleted["deleted"].append("files")

        # 3. Rebuild graph_views
        db_path = ws / "kn_gragh.db"
        if db_path.exists():
            try:
                from kn_graph.services.graph_builder import _build_artifact_from_sqlite, run_build_from_artifact
                artifact = _build_artifact_from_sqlite(db_path)
                views_out = ws / "graph_views.json"
                run_build_from_artifact(artifact, views_out)
                deleted["graph_rebuilt"] = True
            except Exception:
                deleted["graph_rebuilt"] = False

        # 4. Reload
        self._loaded = False
        self._ensure_loaded(library_id)
        return deleted

    def resolve_paper_file(self, paper_id_or_doi: str, library_id: str = "", file_type: str = "") -> dict[str, Any] | None:
        files_payload = self.get_paper_files(paper_id_or_doi, library_id=library_id)
        if files_payload is None:
            return None
        files = files_payload.get("files", {}) if isinstance(files_payload, dict) else {}
        if not isinstance(files, dict):
            files = {}
        preferred = str(file_type or "").strip().lower()
        order = [preferred] if preferred in {"pdf", "markdown", "html"} else []
        for t in ("pdf", "markdown", "html"):
            if t not in order:
                order.append(t)
        for t in order:
            row = files.get(t)
            if not isinstance(row, dict):
                continue
            p = str(row.get("path", "") or "").strip()
            if not p:
                continue
            return {
                "type": t,
                "path": p,
                "name": str(row.get("name", "") or "").strip(),
                "paper_id": files_payload.get("paper_id", paper_id_or_doi),
                "library_id": files_payload.get("library_id", library_id),
            }
        return None

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
        if not paper_ids:
            node_row = self._nodes.get(nid, {}) if isinstance(self._nodes.get(nid), dict) else {}
            profile = node_row.get("paper_profile")
            if isinstance(profile, dict):
                paper_ids = sorted(str(k).strip() for k in profile.keys() if str(k).strip())

        papers_payload: list[dict[str, Any]] = []
        paper_groups: list[dict[str, Any]] = []
        for pid in paper_ids:
            p = self._paper_map_unique.get(pid, {})
            display_pid = pid
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
                mention_row = dict(x)
                mention_row["paper_id_raw"] = pid
                mention_row["paper_id"] = display_pid
                m.append(mention_row)
            local_html, online_url = _paper_links(p, pid)
            variable_name = str(self._nodes.get(nid, {}).get("label") or self._nodes.get(nid, {}).get("name") or "")
            raw_defs = list(p.get("variable_definitions", []) or [])
            concepts = [
                {
                    "variable": str(d.get("variable_name", "") or d.get("variable", "") or "").strip(),
                    "definition": str(d.get("definition", "") or "").strip(),
                    "evidence_section": str(d.get("measurement", "") or "").strip(),
                }
                for d in raw_defs
                if _norm_rel_text(str(d.get("variable_name", "") or d.get("variable", "") or "")) == _norm_rel_text(variable_name)
                and str(d.get("definition", "") or "").strip()
            ]
            operationalization = p.get("variable_definitions", [])
            measurement_methods: list[dict[str, Any]] = []
            if isinstance(operationalization, list):
                for d in operationalization:
                    if not isinstance(d, dict):
                        continue
                    v_txt = str(d.get("variable_name", "") or d.get("variable", "") or "").strip()
                    if _norm_rel_text(v_txt) != _norm_rel_text(variable_name):
                        continue
                    measurement = str(d.get("measurement", "") or "").strip()
                    if measurement:
                        measurement_methods.append(
                            {
                                "variable": v_txt,
                                "operationalized_as": [measurement],
                            }
                        )

            relation_summaries = [_relation_summary_from_mention(item) for item in m]
            papers_payload.append(
                {
                    "paper_id": display_pid,
                    "paper_id_raw": pid,
                    "doi": str(p.get("doi", "") or pid),
                    "publication_year": p.get("publication_year"),
                    "open_local_html": local_html,
                    "open_online_url": online_url,
                    "mentions": m,
                }
            )
            paper_groups.append(
                {
                    "paper_id": display_pid,
                    "paper_id_raw": pid,
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
