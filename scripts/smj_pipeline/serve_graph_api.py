from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import importlib.util
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
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


def _load_literature_service_class():
    module_path = Path(__file__).resolve().parent / "literature" / "service.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_literature_service_for_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LiteratureService


def _load_chat_service_class():
    module_path = Path(__file__).resolve().parent / "chat_service.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_chat_service_for_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.ChatService


def _load_provider_registry_class():
    module_path = Path(__file__).resolve().parent / "llm" / "provider_registry.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_provider_registry_for_serve_graph_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ProviderRegistry


def _load_workspace_layout_store_class():
    module_path = Path(__file__).resolve().parent / "workspace_layout_store.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_workspace_layout_store_for_serve_graph_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.WorkspaceLayoutStore


def _load_agent_runner_module():
    module_path = Path(__file__).resolve().parent / "agent_runner.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_agent_runner_for_serve_graph_api", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _InMemoryWorkspaceLayoutStore:
    def __init__(self) -> None:
        self._layouts: dict[str, dict[str, Any]] = {}

    def save_layout(self, name: str, layout: dict[str, Any]) -> dict[str, Any]:
        key = str(name or "default").strip() or "default"
        now = datetime.now(timezone.utc).isoformat()
        row = {"name": key, "layout": dict(layout), "updated_at": now}
        self._layouts[key] = row
        return dict(row)

    def get_layout(self, name: str) -> dict[str, Any] | None:
        key = str(name or "default").strip() or "default"
        row = self._layouts.get(key)
        return dict(row) if isinstance(row, dict) else None

    def list_layouts(self) -> dict[str, Any]:
        rows = list(self._layouts.values())
        rows.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        return {"layouts": [{"name": str(r.get("name", "")), "updated_at": str(r.get("updated_at", ""))} for r in rows]}


def _scan_literature_libraries(index_root: Path) -> dict[str, Any]:
    libraries: list[dict[str, Any]] = []
    root = index_root.resolve()
    if root.exists() and root.is_dir():
        for fp in sorted(root.glob("*.json")):
            try:
                payload = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            library_id = str(payload.get("library_id", "") or fp.stem).strip()
            if not library_id:
                continue
            updated_at = str(payload.get("updated_at", "") or "").strip()
            paper_count_raw = payload.get("paper_count", 0)
            try:
                paper_count = int(paper_count_raw)
            except Exception:
                paper_ids = payload.get("paper_ids", [])
                paper_count = len(paper_ids) if isinstance(paper_ids, list) else 0
            libraries.append(
                {
                    "library_id": library_id,
                    "paper_count": max(0, paper_count),
                    "updated_at": updated_at,
                    "path": str(fp.resolve()),
                    "workspace_path": str(
                        payload.get("workspace_path", "")
                        or payload.get("library_root", "")
                        or payload.get("root_path", "")
                        or ""
                    ).strip(),
                }
            )
    libraries.sort(key=lambda x: (str(x.get("updated_at", "")), str(x.get("library_id", ""))), reverse=True)
    default_library_id = (os.getenv("LITERATURE_DEFAULT_LIBRARY_ID", "") or "").strip()
    if not default_library_id and libraries:
        default_library_id = str(libraries[0].get("library_id", "") or "")
    return {"libraries": libraries, "default_library_id": default_library_id}


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
    p.add_argument("--frontend-dir", type=Path, default=Path("frontend/graph_3d"))
    p.add_argument("--chat-frontend-dir", type=Path, default=Path("frontend/chat_embed"))
    p.add_argument("--workbench-frontend-dir", type=Path, default=Path("frontend/workbench_spa"))
    p.add_argument("--workspace-layouts-file", type=Path, default=Path("outputs/workbench/workspace_layouts.json"))
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
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(raw)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(raw)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


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
            "title": f"{moderator} \u8c03\u8282 {src} -> {tgt}",
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


def _parse_levels(raw_levels: str) -> list[str]:
    text = (raw_levels or "").strip()
    if not text:
        return ["sentence"]
    out: list[str] = []
    for token in text.split(","):
        item = token.strip().lower()
        if item in {"sentence", "paragraph", "document"}:
            out.append(item)
    return out or ["sentence"]


def make_handler(
    views: dict[str, Any],
    frontend_dir: Path,
    chat_frontend_dir: Path | None = None,
    workbench_frontend_dir: Path | None = None,
    workspace_layouts_file: Path | None = None,
    literature_service: Any | None = None,
    chat_service: Any | None = None,
    workspace_layout_store: Any | None = None,
):
    nodes: dict[str, dict[str, Any]] = views["nodes"]
    edges: list[dict[str, Any]] = views["edges"]
    moderation_links: list[dict[str, Any]] = views.get("moderation_links", [])
    interaction_links: list[dict[str, Any]] = views.get("interaction_links", [])
    edge_index_by_node: dict[str, list[int]] = views["edge_index_by_node"]
    overview = views["overview"]
    paper_map: dict[str, dict[str, Any]] = views["paper_map"]
    meta = views.get("meta", {})
    literature = literature_service
    if literature is None:
        try:
            literature_cls = _load_literature_service_class()
            literature = literature_cls()
        except Exception:
            literature = None
    try:
        provider_registry = _load_provider_registry_class()()
    except Exception:
        provider_registry = None
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
            "source_name": " x ".join(str(v or "") for v in (inter.get("inputs", []) or [])),
            "target_name": str(inter.get("output", "") or node_id_to_name.get(output_id, output_id)),
            "source_name_canonical": " x ".join(node_id_to_name.get(nid, nid) for nid in input_ids),
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
    relation_var_names: set[str] = set()
    for edge in edges:
        source_id = str(edge.get("source", "") or "").strip()
        target_id = str(edge.get("target", "") or "").strip()
        if source_id and source_id in node_id_to_name:
            norm = _norm_rel_text(node_id_to_name.get(source_id, ""))
            if norm:
                relation_var_names.add(norm)
        if target_id and target_id in node_id_to_name:
            norm = _norm_rel_text(node_id_to_name.get(target_id, ""))
            if norm:
                relation_var_names.add(norm)
        for key in ("source_name_local", "source_name", "source"):
            txt = str(edge.get(key, "") or "").strip()
            norm = _norm_rel_text(txt)
            if norm:
                relation_var_names.add(norm)
                break
        for key in ("target_name_local", "target_name", "target"):
            txt = str(edge.get(key, "") or "").strip()
            norm = _norm_rel_text(txt)
            if norm:
                relation_var_names.add(norm)
                break
    for mod in moderation_links:
        moderator = str(mod.get("moderator_var", "") or "").strip()
        relation = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
        src = str(relation.get("source_var", "") or "").strip()
        tgt = str(relation.get("target_var", "") or "").strip()
        for txt in (moderator, src, tgt):
            norm = _norm_rel_text(txt)
            if norm:
                relation_var_names.add(norm)
    for inter in interaction_links:
        output = str(inter.get("output", "") or "").strip()
        norm_output = _norm_rel_text(output)
        if norm_output:
            relation_var_names.add(norm_output)
        for inp in inter.get("inputs", []) or []:
            norm = _norm_rel_text(str(inp or "").strip())
            if norm:
                relation_var_names.add(norm)

    definition_entries_by_var: dict[str, list[dict[str, Any]]] = {}
    definition_var_names: set[str] = set()
    for pid, paper in paper_map_unique.items():
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
            definition_var_names.add(norm)
            definition_entries_by_var.setdefault(norm, []).append(
                {
                    "paper_id": pid,
                    "publication_year": publication_year,
                    "variable": variable,
                    "definition": definition,
                    "evidence_section": evidence,
                    "theories": theories,
                }
            )

    degree_by_node: dict[str, int] = {nid: 0 for nid in nodes}
    for edge in edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source in degree_by_node:
            degree_by_node[source] += 1
        if target in degree_by_node:
            degree_by_node[target] += 1

    nodes_public_by_id: dict[str, dict[str, Any]] = {}
    isolated_nodes: list[dict[str, Any]] = []
    for nid, node in nodes.items():
        payload = dict(node)
        node_type = str(node.get("type", "")).strip()
        norm_label = _norm_rel_text(str(node.get("label") or node.get("name") or nid))
        in_rel = bool(norm_label and norm_label in relation_var_names)
        in_defs = bool(norm_label and norm_label in definition_var_names)
        is_validated = bool(in_rel or in_defs)
        degree = int(degree_by_node.get(nid, 0))
        payload["validated_variable"] = is_validated if node_type == "variable" else True
        payload["relation_degree"] = degree
        payload["is_isolated"] = bool(node_type == "variable" and degree == 0)
        payload["library_name"] = "\u4f9b\u5e94\u94fe"

        if norm_label and norm_label in definition_entries_by_var:
            entries = definition_entries_by_var.get(norm_label, [])
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
            if not is_validated:
                reason = "unvalidated"
            elif in_defs and not in_rel:
                reason = "definition_only"
            elif in_rel and not in_defs:
                reason = "relation_only"
            else:
                reason = "no_relation_extracted"
            isolated_nodes.append(
                {
                    "node_id": nid,
                    "label": str(node.get("label") or node.get("name") or nid),
                    "reason": reason,
                }
            )
        nodes_public_by_id[nid] = payload

    meta_public = dict(meta)
    meta_public["isolated_node_count"] = len(isolated_nodes)
    meta_public["dataset_library_name"] = "\u4f9b\u5e94\u94fe"

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

    def _graph_search_cards(
        query: str,
        mode: str = "variable",
        limit: int = 20,
        keyword_weight: float = 0.5,
        vector_weight: float = 0.5,
        requested_backend: str = "hash",
    ) -> dict[str, Any]:
        query_text = str(query or "").strip().lower()
        if not query_text:
            return {"results": [], "search_meta": {"vector_backend_requested": requested_backend, "vector_backend_used": "hash"}}
        q_tokens = set(_tokenize(query_text))
        q_emb = _hash_embedding(query_text)
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
        return {
            "results": [p for _, p in ranked[:limit]],
            "search_meta": {
                "vector_backend_requested": requested_backend,
                "vector_backend_used": backend_used,
                "note": backend_note,
            },
        }

    def _paper_get(paper_id_or_doi: str) -> dict[str, Any] | None:
        pid = str(paper_id_or_doi or "").strip()
        if not pid:
            return None
        obj = paper_map.get(pid)
        if obj is None:
            for candidate in paper_map.values():
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

    def _variable_get(node_id: str) -> dict[str, Any] | None:
        nid = str(node_id or "").strip()
        if nid not in nodes:
            return None
        mentions = node_mentions.get(nid, [])
        edge_paper_ids = node_to_papers_edge.get(nid, set())
        moderation_paper_ids = node_to_papers_moderation.get(nid, set())
        interaction_paper_ids = node_to_papers_interaction.get(nid, set())
        paper_ids = sorted(edge_paper_ids.union(moderation_paper_ids).union(interaction_paper_ids))
        return {
            "node": nodes[nid],
            "paper_count_total": len(paper_ids),
            "paper_count_edge": len(edge_paper_ids),
            "paper_count_moderation": len(moderation_paper_ids),
            "paper_count_interaction": len(interaction_paper_ids),
            "paper_count": len(paper_ids),
            "mentions": mentions[:50],
        }

    libraries_index_root = Path(os.getenv("LITERATURE_LIBRARY_INDEX_ROOT", "outputs/literature_libraries") or "outputs/literature_libraries")

    def _resolve_library_workspace(library_id: str) -> str:
        payload = _scan_literature_libraries(libraries_index_root)
        rows = payload.get("libraries", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        target = str(library_id or payload.get("default_library_id", "") or "").strip()
        if not target:
            return ""
        for item in rows:
            if not isinstance(item, dict):
                continue
            if str(item.get("library_id", "") or "").strip() != target:
                continue
            workspace = str(item.get("workspace_path", "") or "").strip()
            if workspace:
                return workspace
            idx_file = str(item.get("path", "") or "").strip()
            if idx_file:
                return str(Path(idx_file).resolve().parent)
            break
        return ""

    codex_config_path = Path(os.getenv("CHAT_CODEX_CONFIG_PATH", "outputs/chat/codex_runner_config.json") or "outputs/chat/codex_runner_config.json")
    try:
        _agent_runner_mod = _load_agent_runner_module()
    except Exception:
        _agent_runner_mod = None

    def _load_codex_config_payload() -> dict[str, Any]:
        if _agent_runner_mod is None:
            return {}
        cfg = _agent_runner_mod.load_codex_config(codex_config_path)
        return {
            "cli_command": str(cfg.cli_command or ""),
            "cli_args": list(cfg.cli_args),
            "healthcheck_args": list(cfg.healthcheck_args),
            "timeout_seconds": int(cfg.timeout_seconds),
            "install_command": str(cfg.install_command or ""),
            "extra_env": dict(cfg.extra_env),
            "config_path": str(codex_config_path.resolve()),
        }

    def _save_codex_config_payload(body: dict[str, Any]) -> dict[str, Any]:
        codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_codex_config_payload()
        next_payload = dict(existing)
        for key in ("cli_command", "cli_args", "healthcheck_args", "timeout_seconds", "install_command", "extra_env"):
            if key in body:
                next_payload[key] = body.get(key)
        to_write = {k: v for k, v in next_payload.items() if k != "config_path"}
        codex_config_path.write_text(json.dumps(to_write, ensure_ascii=False, indent=2), encoding="utf-8")
        return _load_codex_config_payload()

    chat = chat_service
    if chat is None:
        try:
            chat_cls = _load_chat_service_class()
            chat = chat_cls(
                literature_search_fn=lambda q, k, library_id="": (
                    literature.search(
                        query=q,
                        top_k=k,
                        levels=["sentence", "paragraph"],
                        library_id=library_id,
                        keyword_weight=0.4,
                        rag_weight=0.6,
                        include_expanded_context=True,
                    )
                    if literature is not None
                    else {"keyword_hits": [], "rag_hits": [], "merged_hits": []}
                ),
                graph_search_fn=lambda q, k: list(_graph_search_cards(query=q, mode="variable", limit=k).get("results", []))
                + list(_graph_search_cards(query=q, mode="paper", limit=max(1, k // 2)).get("results", [])),
                paper_get_fn=_paper_get,
                variable_get_fn=_variable_get,
                library_workspace_resolver_fn=_resolve_library_workspace,
            )
        except Exception:
            chat = None

    workspace_store = workspace_layout_store
    workspace_store_degraded_reason = ""
    if workspace_store is None:
        try:
            workspace_cls = _load_workspace_layout_store_class()
            workspace_store = workspace_cls(storage_path=workspace_layouts_file)
        except Exception as exc:
            workspace_store = _InMemoryWorkspaceLayoutStore()
            workspace_store_degraded_reason = f"workspace_layout_store_loader_failed:{exc}"

    def _workspace_with_degraded(payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        if workspace_store_degraded_reason:
            out["degraded"] = True
            out["degraded_reason"] = workspace_store_degraded_reason
        return out

    class Handler(BaseHTTPRequestHandler):
        def _read_json_body(self) -> dict[str, Any]:
            raw_len = int(self.headers.get("Content-Length", "0") or "0")
            if raw_len <= 0:
                return {}
            raw = self.rfile.read(raw_len).decode("utf-8", errors="ignore")
            if not raw.strip():
                return {}
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("json body must be object")
            return payload

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/chat/codex/config":
                try:
                    body = self._read_json_body()
                    if not isinstance(body, dict):
                        return _json(self, {"error": "invalid_payload"}, status=400)
                    saved = _save_codex_config_payload(body)
                    return _json(self, {"ok": True, "config": saved}, status=200)
                except Exception as exc:
                    return _json(self, {"error": "codex_config_save_failed", "detail": str(exc)}, status=400)

            if path == "/chat/codex/install":
                try:
                    cfg = _load_codex_config_payload()
                    install_cmd = str(cfg.get("install_command", "") or "").strip()
                    if not install_cmd:
                        return _json(self, {"error": "codex_install_command_missing"}, status=400)
                    proc = subprocess.run(
                        shlex.split(install_cmd),
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=900,
                    )
                    payload = {
                        "ok": int(proc.returncode) == 0,
                        "returncode": int(proc.returncode),
                        "stdout": str(proc.stdout or "")[-4000:],
                        "stderr": str(proc.stderr or "")[-4000:],
                    }
                    status = 200 if payload["ok"] else 500
                    return _json(self, payload, status=status)
                except Exception as exc:
                    return _json(self, {"error": "codex_install_failed", "detail": str(exc)}, status=500)

            if path == "/chat/provider-test":
                if provider_registry is None:
                    return _json(self, {"error": "provider_config_unavailable"}, status=503)
                try:
                    body = self._read_json_body()
                    provider = str(body.get("provider", "") or "").strip().lower()
                    provider_item = body.get("provider_item")
                    model = str(body.get("model", "") or "").strip()
                    options = body.get("options", {})
                    prompt = str(body.get("prompt", "") or "").strip() or "Reply with OK only."
                    if not isinstance(options, dict):
                        options = {}

                    active_registry = provider_registry
                    if isinstance(provider_item, dict):
                        item_id = str(provider_item.get("id", "") or "").strip().lower()
                        if not item_id:
                            return _json(self, {"error": "provider_id_required"}, status=400)
                        payload = provider_registry.get_config()
                        providers = payload.get("providers", [])
                        if not isinstance(providers, list):
                            providers = []
                        replaced = False
                        next_providers: list[dict[str, Any]] = []
                        for item in providers:
                            if not isinstance(item, dict):
                                continue
                            if str(item.get("id", "") or "").strip().lower() == item_id:
                                next_providers.append(dict(provider_item))
                                replaced = True
                            else:
                                next_providers.append(dict(item))
                        if not replaced:
                            next_providers.append(dict(provider_item))
                        payload["default_provider"] = item_id
                        payload["providers"] = next_providers
                        tmp_registry_cls = _load_provider_registry_class()
                        active_registry = tmp_registry_cls(config_path=provider_registry.config_path)
                        if not hasattr(active_registry, "_apply_payload"):
                            raise RuntimeError("provider_registry_apply_payload_missing")
                        active_registry._apply_payload(payload)  # type: ignore[attr-defined]
                        provider = item_id

                    if not provider:
                        return _json(self, {"error": "provider_required"}, status=400)

                    resolved = active_registry.resolve_provider_id(provider)
                    if not model:
                        cfg = active_registry.get_config()
                        providers = cfg.get("providers", []) if isinstance(cfg, dict) else []
                        if isinstance(providers, list):
                            for item in providers:
                                if not isinstance(item, dict):
                                    continue
                                if str(item.get("id", "") or "").strip().lower() == resolved:
                                    model = str(item.get("default_model", "") or "").strip()
                                    break

                    timeout_seconds = int(options.get("timeout_seconds", 20) or 20)
                    client = active_registry.create_message_client(
                        provider=provider,
                        model=model or None,
                        options=options,
                    )
                    text = str(
                        client.complete_messages(
                            messages=[
                                {"role": "system", "content": "You are a connection checker. Keep responses minimal."},
                                {"role": "user", "content": prompt},
                            ],
                            timeout_seconds=timeout_seconds,
                        )
                    ).strip()
                    return _json(
                        self,
                        {
                            "ok": True,
                            "provider": resolved,
                            "model": model,
                            "response_preview": text[:120],
                        },
                    )
                except Exception as exc:
                    return _json(self, {"error": "provider_test_failed", "detail": str(exc)}, status=400)

            if path == "/chat/provider-config":
                if provider_registry is None:
                    return _json(self, {"error": "provider_config_unavailable"}, status=503)
                try:
                    body = self._read_json_body()
                    if not isinstance(body, dict):
                        return _json(self, {"error": "invalid_payload"}, status=400)
                    saved = provider_registry.update_config(body)
                    saved["config_path"] = str(provider_registry.config_path)
                    return _json(self, {"ok": True, "config": saved}, status=200)
                except Exception as exc:
                    return _json(self, {"error": "provider_config_save_failed", "detail": str(exc)}, status=400)

            if path == "/chat/sessions":
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                try:
                    body = self._read_json_body()
                    title = str(body.get("title", "") or "")
                    payload = chat.create_session(title=title, default_mode="agent")
                    return _json(self, payload, status=201)
                except Exception as exc:
                    return _json(self, {"error": "chat_create_session_failed", "detail": str(exc)}, status=500)

            if path.startswith("/chat/sessions/") and path.endswith("/messages"):
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                try:
                    prefix = "/chat/sessions/"
                    middle = path[len(prefix) : -len("/messages")]
                    session_id = str(middle).strip()
                    if not session_id:
                        return _json(self, {"error": "session_id_required"}, status=400)
                    body = self._read_json_body()
                    content = str(body.get("content", "") or "").strip()
                    if not content:
                        return _json(self, {"error": "content_required"}, status=400)
                    mode = "agent"
                    provider = "codex"
                    model = "codex-local"
                    stream = bool(body.get("stream", True))
                    library_id = str(body.get("library_id", "") or "").strip()
                    payload = chat.submit_message(
                        session_id=session_id,
                        content=content,
                        mode=mode,
                        provider=provider,
                        model=model,
                        stream=stream,
                        library_id=library_id,
                    )
                    return _json(
                        self,
                        {
                            "session_id": session_id,
                            "assistant_message_id": payload.get("assistant_message_id"),
                            "user_message_id": payload.get("user_message_id"),
                            "stream_url": f"/chat/sessions/{session_id}/stream?message_id={payload.get('assistant_message_id','')}",
                        },
                        status=202,
                    )
                except KeyError:
                    return _json(self, {"error": "session_not_found"}, status=404)
                except Exception as exc:
                    return _json(self, {"error": "chat_submit_failed", "detail": str(exc)}, status=500)

            if path.startswith("/chat/sessions/") and path.endswith("/restore"):
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                try:
                    prefix = "/chat/sessions/"
                    session_id = str(path[len(prefix) : -len("/restore")]).strip().rstrip("/")
                    if not session_id:
                        return _json(self, {"error": "session_id_required"}, status=400)
                    payload = chat.restore_session(session_id)
                    if not isinstance(payload, dict):
                        return _json(self, {"error": "chat_restore_failed"}, status=500)
                    if not bool(payload.get("restored")):
                        error = str(payload.get("error", "restore_failed") or "restore_failed")
                        status_code = 409 if error == "restore_window_expired" else 404
                        return _json(self, {"error": error, "session_id": session_id}, status=status_code)
                    return _json(self, payload, status=200)
                except Exception as exc:
                    return _json(self, {"error": "chat_restore_failed", "detail": str(exc)}, status=500)

            if path == "/literature/import":
                if literature is None:
                    return _json(self, {"error": "literature_service_unavailable"}, status=503)
                try:
                    body = self._read_json_body()
                    manifest_path = str(body.get("manifest_path", "") or "").strip()
                    if not manifest_path:
                        return _json(self, {"error": "manifest_path_required"}, status=400)
                    options = body.get("options", {})
                    if not isinstance(options, dict):
                        options = {}
                    library_id = str(body.get("library_id", "") or "").strip()
                    if library_id and "library_id" not in options:
                        options["library_id"] = library_id
                    result = literature.import_manifest(manifest_path, options=options if isinstance(options, dict) else None)
                    return _json(self, result)
                except Exception as exc:
                    return _json(self, {"error": "literature_import_failed", "detail": str(exc)}, status=500)

            if path == "/literature/answer":
                try:
                    body = self._read_json_body()
                    query = str(body.get("query", "") or "").strip()
                    if not query:
                        return _json(self, {"error": "query_required"}, status=400)
                    top_k = int(body.get("top_k", 5) or 5)
                    levels = body.get("levels")
                    if isinstance(levels, list):
                        parsed_levels = [str(x).strip().lower() for x in levels if str(x).strip()]
                    else:
                        parsed_levels = _parse_levels(str(levels or "sentence"))
                    library_id = str(body.get("library_id", "") or "").strip()
                    keyword_weight = float(body.get("keyword_weight", 0.4) or 0.4)
                    rag_weight = float(body.get("rag_weight", 0.6) or 0.6)
                    if literature is None:
                        return _json(
                            self,
                            {
                                "answer": "当前文献服务暂不可用，已降级返回空引用结果。",
                                "citations": [],
                                "retrieval": {
                                    "keyword_hits": [],
                                    "rag_hits": [],
                                    "merged_hits": [],
                                },
                                "degraded": True,
                                "degraded_reason": "literature_service_unavailable",
                                "query": query,
                                "library_id": library_id,
                            },
                        )
                    result = literature.answer(
                        query=query,
                        top_k=top_k,
                        levels=parsed_levels,
                        library_id=library_id,
                        keyword_weight=keyword_weight,
                        rag_weight=rag_weight,
                    )
                    return _json(self, result)
                except Exception as exc:
                    return _json(self, {"error": "literature_answer_failed", "detail": str(exc)}, status=500)

            if path == "/api/v2/workspace/layout":
                try:
                    body = self._read_json_body()
                    name = str(body.get("name", "default") or "default").strip()
                    if not name:
                        return _json(self, {"error": "name_required"}, status=400)
                    layout = body.get("layout")
                    if not isinstance(layout, dict):
                        return _json(self, {"error": "layout_object_required"}, status=400)
                    saved = workspace_store.save_layout(name=name, layout=layout)
                    return _json(self, _workspace_with_degraded(saved), status=200)
                except Exception as exc:
                    return _json(self, {"error": "workspace_layout_save_failed", "detail": str(exc)}, status=500)

            self.send_error(404, "Not Found")

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path.startswith("/chat/sessions/"):
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                try:
                    session_id = str(path[len("/chat/sessions/") :]).strip().rstrip("/")
                    if not session_id:
                        return _json(self, {"error": "session_id_required"}, status=400)
                    payload = chat.delete_session(session_id=session_id, undo_window_seconds=5)
                    return _json(self, payload, status=200)
                except KeyError:
                    return _json(self, {"error": "session_not_found"}, status=404)
                except Exception as exc:
                    return _json(self, {"error": "chat_delete_session_failed", "detail": str(exc)}, status=500)

            self.send_error(404, "Not Found")

        def _serve_static(self, rel_path: str) -> None:
            safe = rel_path.lstrip("/")
            if not safe or safe == "frontend":
                safe = "index.html"
            path = (frontend_dir / safe).resolve()
            if not str(path).startswith(str(frontend_dir.resolve())) or not path.exists() or not path.is_file():
                self.send_error(404, "Not Found")
                return
            raw = path.read_bytes()
            if path.name.lower() == "index.html":
                try:
                    text = raw.decode("utf-8", errors="ignore")
                    if "id=\"kn-chat-entry\"" not in text:
                        entry = (
                            "<a id=\"kn-chat-entry\" href=\"/frontend/chat/\" "
                            "style=\"position:fixed;right:20px;bottom:20px;z-index:9999;"
                            "background:#0f766e;color:#fff;text-decoration:none;padding:10px 14px;"
                            "border-radius:999px;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.2);\">AI \u95ee\u7b54</a>"
                        )
                        if "</body>" in text:
                            text = text.replace("</body>", entry + "</body>")
                        else:
                            text += entry
                        raw = text.encode("utf-8")
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", _guess_content_type(path))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _serve_chat_static(self, rel_path: str) -> None:
            root = (chat_frontend_dir or Path("frontend/chat_embed")).resolve()
            safe = rel_path.lstrip("/")
            if not safe:
                safe = "index.html"
            path = (root / safe).resolve()
            if not str(path).startswith(str(root)) or not path.exists() or not path.is_file():
                self.send_error(404, "Not Found")
                return
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _guess_content_type(path))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _serve_workbench_static(self, rel_path: str) -> None:
            root = (workbench_frontend_dir or Path("frontend/workbench_spa")).resolve()
            safe = rel_path.lstrip("/")
            if not safe:
                safe = "index.html"
            path = (root / safe).resolve()
            if not str(path).startswith(str(root)) or not path.exists() or not path.is_file():
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

            if path == "/chat/sessions":
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                try:
                    payload = {"sessions": chat.list_sessions()}
                    return _json(self, payload)
                except Exception as exc:
                    return _json(self, {"error": "chat_list_sessions_failed", "detail": str(exc)}, status=500)

            if path == "/chat/codex/config":
                try:
                    return _json(self, {"config": _load_codex_config_payload()}, status=200)
                except Exception as exc:
                    return _json(self, {"error": "codex_config_load_failed", "detail": str(exc)}, status=500)

            if path == "/chat/codex/health":
                if _agent_runner_mod is None:
                    return _json(self, {"backend": "codex", "available": False, "reason": "agent_runner_module_unavailable"}, status=503)
                try:
                    cfg = _agent_runner_mod.load_codex_config(codex_config_path)
                    runner = _agent_runner_mod.CodexRunner(cfg)
                    payload = runner.health()
                    payload["config_path"] = str(codex_config_path.resolve())
                    status = 200 if bool(payload.get("available")) else 503
                    return _json(self, payload, status=status)
                except Exception as exc:
                    return _json(self, {"backend": "codex", "available": False, "reason": str(exc)}, status=503)

            if path == "/chat/provider-config":
                if provider_registry is None:
                    return _json(self, {"error": "provider_config_unavailable"}, status=503)
                try:
                    provider_registry.reload()
                    payload = provider_registry.get_config()
                    payload["config_path"] = str(provider_registry.config_path)
                    return _json(self, payload)
                except Exception as exc:
                    return _json(self, {"error": "provider_config_load_failed", "detail": str(exc)}, status=500)

            if path.startswith("/chat/sessions/") and path.endswith("/stream"):
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                prefix = "/chat/sessions/"
                session_id = str(path[len(prefix) : -len("/stream")]).strip().rstrip("/")
                message_id = str((qs.get("message_id", [""])[0] or "")).strip()
                if not session_id:
                    return _json(self, {"error": "session_id_required"}, status=400)
                if not message_id:
                    return _json(self, {"error": "message_id_required"}, status=400)
                cursor = int((qs.get("cursor", ["0"])[0] or "0"))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for _ in range(0, 240):
                        rows, cursor, done = chat.read_events(message_id=message_id, cursor=cursor, wait_seconds=5.0)
                        for row in rows:
                            event_type = str(row.get("type", "delta") or "delta")
                            payload = {
                                "session_id": session_id,
                                "message_id": message_id,
                                "cursor": cursor,
                                **(row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}),
                            }
                            line = f"event: {event_type}\n" + "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                            self.wfile.write(line.encode("utf-8"))
                            self.wfile.flush()
                        if done:
                            break
                        heartbeat = "event: heartbeat\ndata: {}\n\n"
                        self.wfile.write(heartbeat.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                self.close_connection = True
                return

            if path.startswith("/chat/sessions/") and not path.endswith("/stream"):
                if chat is None:
                    return _json(self, {"error": "chat_service_unavailable"}, status=503)
                session_id = str(path[len("/chat/sessions/") :]).strip().rstrip("/")
                if not session_id:
                    return _json(self, {"error": "session_id_required"}, status=400)
                try:
                    payload = chat.get_session_with_messages(session_id)
                    if payload is None:
                        return _json(self, {"error": "session_not_found", "session_id": session_id}, status=404)
                    return _json(self, payload)
                except Exception as exc:
                    return _json(self, {"error": "chat_get_session_failed", "detail": str(exc)}, status=500)

            if path == "/literature/search":
                query = (qs.get("query", qs.get("q", [""]))[0] or "").strip()
                if not query:
                    return _json(self, {"error": "query_required"}, status=400)
                top_k = int((qs.get("top_k", qs.get("limit", ["20"]))[0] or "20"))
                raw_levels = (qs.get("levels", ["sentence"])[0] or "sentence").strip()
                levels = _parse_levels(raw_levels)
                library_id = (qs.get("library_id", [""])[0] or "").strip()
                include_expanded_context = (qs.get("include_expanded_context", ["true"])[0] or "true").strip().lower() in {"1", "true", "yes"}
                keyword_weight = float((qs.get("keyword_weight", ["0.4"])[0] or "0.4"))
                rag_weight = float((qs.get("rag_weight", ["0.6"])[0] or "0.6"))
                if literature is None:
                    return _json(
                        self,
                        {
                            "query": query,
                            "library_id": library_id,
                            "top_k": top_k,
                            "levels": levels,
                            "keyword_hits": [],
                            "rag_hits": [],
                            "merged_hits": [],
                            "degraded": True,
                            "degraded_reason": "literature_service_unavailable",
                        },
                    )
                try:
                    payload = literature.search(
                        query=query,
                        top_k=top_k,
                        levels=levels,
                        library_id=library_id,
                        keyword_weight=keyword_weight,
                        rag_weight=rag_weight,
                        include_expanded_context=include_expanded_context,
                    )
                except Exception as exc:
                    return _json(self, {"error": "literature_search_failed", "detail": str(exc)}, status=500)
                return _json(self, payload)

            if path == "/literature/libraries":
                root = Path(os.getenv("LITERATURE_LIBRARY_INDEX_ROOT", "outputs/literature_libraries") or "outputs/literature_libraries")
                return _json(self, _scan_literature_libraries(root))

            if path == "/api/v2/workspace/layouts":
                try:
                    payload = workspace_store.list_layouts()
                    if not isinstance(payload, dict):
                        payload = {"layouts": payload if isinstance(payload, list) else []}
                    return _json(self, _workspace_with_degraded(payload))
                except Exception as exc:
                    return _json(self, {"error": "workspace_layout_list_failed", "detail": str(exc)}, status=500)

            if path == "/api/v2/workspace/layout":
                name = str((qs.get("name", ["default"])[0] or "default")).strip() or "default"
                try:
                    payload = workspace_store.get_layout(name=name)
                    if payload is None:
                        return _json(self, {"error": "workspace_layout_not_found", "name": name}, status=404)
                    return _json(self, _workspace_with_degraded(payload))
                except Exception as exc:
                    return _json(self, {"error": "workspace_layout_get_failed", "detail": str(exc)}, status=500)

            if path in ("/", "/frontend", "/frontend/"):
                return self._serve_static("index.html")
            if path in ("/frontend/workbench", "/frontend/workbench/"):
                return self._serve_workbench_static("index.html")
            if path.startswith("/frontend/workbench/"):
                return self._serve_workbench_static(path[len("/frontend/workbench/") :])
            if path in ("/frontend/chat", "/frontend/chat/"):
                return self._serve_chat_static("index.html")
            if path.startswith("/frontend/chat/"):
                return self._serve_chat_static(path[len("/frontend/chat/") :])
            if path.startswith("/frontend/"):
                return self._serve_static(path[len("/frontend/") :])

            if path == "/graph/overview":
                node_ids = overview["node_ids"]
                edge_indexes = overview["edge_indexes"]
                payload = {
                    "meta": meta_public,
                    "nodes": [nodes_public_by_id[nid] for nid in node_ids if nid in nodes_public_by_id],
                    "edges": [edges[i] for i in edge_indexes if 0 <= i < len(edges)],
                    "moderation_links": moderation_links,
                    "interaction_links": interaction_links,
                    "isolated_nodes": isolated_nodes,
                }
                return _json(self, payload)

            if path == "/graph/full":
                payload = {
                    "meta": meta_public,
                    "nodes": list(nodes_public_by_id.values()),
                    "edges": edges,
                    "moderation_links": moderation_links,
                    "interaction_links": interaction_links,
                    "paper_map": paper_map_unique,
                    "isolated_nodes": isolated_nodes,
                }
                return _json(self, payload)

            if path == "/graph/search":
                query = (qs.get("query", qs.get("q", [""]))[0] or "").strip().lower()
                mode = (qs.get("mode", ["variable"])[0] or "variable").strip().lower()
                limit = int((qs.get("limit", qs.get("top_k", ["20"]))[0] or "20"))
                keyword_weight = float((qs.get("keyword_weight", ["0.5"])[0] or "0.5"))
                vector_weight = float((qs.get("vector_weight", ["0.5"])[0] or "0.5"))
                requested_backend = (qs.get("vector_backend", ["hash"])[0] or "hash").strip().lower()
                return _json(
                    self,
                    _graph_search_cards(
                        query=query,
                        mode=mode,
                        limit=limit,
                        keyword_weight=keyword_weight,
                        vector_weight=vector_weight,
                        requested_backend=requested_backend,
                    ),
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
                    "nodes": [nodes_public_by_id[nid] for nid in seen_nodes if nid in nodes_public_by_id],
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
                    "node": nodes_public_by_id.get(node_id, nodes[node_id]),
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
    handler = make_handler(
        views,
        args.frontend_dir,
        chat_frontend_dir=args.chat_frontend_dir,
        workbench_frontend_dir=args.workbench_frontend_dir,
        workspace_layouts_file=args.workspace_layouts_file,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Graph API serving: http://{args.host}:{args.port}/frontend/")
    print(f"Using graph views: {views_json}")
    server.serve_forever()


if __name__ == "__main__":
    main()















