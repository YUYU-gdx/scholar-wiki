from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SUPPLY_CHAIN_ROOT = Path("outputs/smj_supply_chain_batch").resolve()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build optimized graph views from full frontend artifact.")
    p.add_argument(
        "--input-json",
        type=Path,
        default=Path("outputs/smj_supply_chain_batch/supply_chain_merged_20260414_113031/frontend_artifact.json"),
    )
    p.add_argument(
        "--output-json",
        type=Path,
        default=Path("outputs/smj_supply_chain_batch/supply_chain_merged_20260414_113031/graph_views.json"),
    )
    p.add_argument("--overview-limit", type=int, default=700)
    p.add_argument("--allow-non-supply-chain", action="store_true")
    return p.parse_args()


def _build_position(i: int, n: int, radius: float = 180.0) -> tuple[float, float, float]:
    # Fibonacci sphere layout for stable, precomputed coordinates.
    if n <= 1:
        return (0.0, 0.0, 0.0)
    phi = math.pi * (3.0 - math.sqrt(5.0))
    y = 1.0 - (2.0 * i) / (n - 1)
    r = math.sqrt(max(0.0, 1.0 - y * y))
    theta = phi * i
    x = math.cos(theta) * r
    z = math.sin(theta) * r
    return (x * radius, y * radius, z * radius)


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _enforce_supply_chain_path(path: Path, allow_non_supply_chain: bool, flag_name: str) -> None:
    resolved = path.resolve()
    if allow_non_supply_chain:
        return
    if SUPPLY_CHAIN_ROOT not in resolved.parents and resolved != SUPPLY_CHAIN_ROOT:
        raise RuntimeError(
            f"{flag_name} path is outside supply-chain scope: {resolved}\n"
            f"allowed root: {SUPPLY_CHAIN_ROOT}\n"
            "use --allow-non-supply-chain to override explicitly"
        )

def _entropy_from_counts(counts: list[int]) -> float:
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    probs = [c / total for c in counts if c > 0]
    if len(probs) <= 1:
        return 0.0
    h = -sum(p * math.log(p) for p in probs)
    h_max = math.log(len(probs))
    if h_max <= 0:
        return 0.0
    return round(h / h_max, 6)


def main() -> None:
    args = parse_args()
    _enforce_supply_chain_path(args.input_json, args.allow_non_supply_chain, "--input-json")
    _enforce_supply_chain_path(args.output_json, args.allow_non_supply_chain, "--output-json")
    data = json.loads(args.input_json.read_text(encoding="utf-8"))

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    moderation_links = data.get("moderation_links", [])
    interaction_links = data.get("interaction_links", [])
    papers = data.get("papers", [])

    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node.get("id", "")).strip()
        if not node_id:
            continue
        node_map[node_id] = dict(node)

    edge_index_by_node: dict[str, list[int]] = {}
    degree: dict[str, int] = {}
    for idx, edge in enumerate(edges):
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if not s or not t:
            continue
        edge_index_by_node.setdefault(s, []).append(idx)
        edge_index_by_node.setdefault(t, []).append(idx)
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1

    # Node-level paper profile for paper-cluster layout.
    node_paper_counts: dict[str, dict[str, int]] = {}
    for edge in edges:
        pid = str(edge.get("paper_id", "")).strip()
        if not pid:
            continue
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if s:
            d = node_paper_counts.setdefault(s, {})
            d[pid] = d.get(pid, 0) + 1
        if t:
            d = node_paper_counts.setdefault(t, {})
            d[pid] = d.get(pid, 0) + 1
    for mod in moderation_links:
        pid = str(mod.get("paper_id", "")).strip()
        if not pid:
            continue
        mr = mod.get("moderated_relation") if isinstance(mod.get("moderated_relation"), dict) else {}
        ids = [
            str(mod.get("moderator_node_id", "")).strip(),
            str(mr.get("source_node_id", "")).strip(),
            str(mr.get("target_node_id", "")).strip(),
        ]
        for nid in ids:
            if not nid:
                continue
            d = node_paper_counts.setdefault(nid, {})
            d[pid] = d.get(pid, 0) + 1
    for inter in interaction_links:
        pid = str(inter.get("paper_id", "")).strip()
        if not pid:
            continue
        ids = [str(v).strip() for v in (inter.get("input_node_ids", []) or []) if str(v).strip()]
        out = str(inter.get("output_node_id", "")).strip()
        if out:
            ids.append(out)
        for nid in ids:
            d = node_paper_counts.setdefault(nid, {})
            d[pid] = d.get(pid, 0) + 1

    for node_id, node in node_map.items():
        profile = node_paper_counts.get(node_id, {})
        top_items = sorted(profile.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        node["paper_profile"] = {k: v for k, v in top_items}
        node["paper_count_mentions"] = int(sum(profile.values()))
        node["dominant_paper_id"] = top_items[0][0] if top_items else ""
        node["paper_entropy"] = _entropy_from_counts([v for _, v in top_items])

    # Backfill first_year for old artifacts that don't carry it yet.
    year_by_node: dict[str, list[int]] = {}
    for edge in edges:
        year = _coerce_int(edge.get("paper_year"))
        if year is None:
            continue
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if s:
            year_by_node.setdefault(s, []).append(year)
        if t:
            year_by_node.setdefault(t, []).append(year)
    for node_id, node in node_map.items():
        if node.get("first_year") is None and node_id in year_by_node:
            node["first_year"] = min(year_by_node[node_id])

    variable_nodes = [n for n in node_map.values() if n.get("type") == "variable"]
    variable_nodes.sort(key=lambda n: degree.get(str(n.get("id", "")), 0), reverse=True)
    overview_nodes = variable_nodes[: args.overview_limit]
    overview_ids = {str(n["id"]) for n in overview_nodes}

    overview_edges: list[int] = []
    for idx, edge in enumerate(edges):
        s = str(edge.get("source", "")).strip()
        t = str(edge.get("target", "")).strip()
        if s in overview_ids and t in overview_ids:
            overview_edges.append(idx)

    # Attach stable precomputed positions for overview.
    for i, node in enumerate(overview_nodes):
        x, y, z = _build_position(i, len(overview_nodes))
        node["x"] = x
        node["y"] = y
        node["z"] = z

    paper_map: dict[str, dict[str, Any]] = {}
    for p in papers:
        paper_id = str(p.get("paper_id", "")).strip()
        doi = str(p.get("doi", "")).strip()
        if paper_id:
            paper_map[paper_id] = p
        if doi and doi not in paper_map:
            paper_map[doi] = p

    meta = dict(data.get("meta", {}))
    meta["dataset_source"] = str(args.input_json)
    meta["dataset_scope"] = "supply_chain"
    if "year_range" not in meta:
        years = [int(v["first_year"]) for v in node_map.values() if _coerce_int(v.get("first_year")) is not None]
        meta["year_range"] = {"min": min(years) if years else None, "max": max(years) if years else None}

    result = {
        "meta": meta,
        "nodes": node_map,
        "edges": edges,
        "moderation_links": moderation_links,
        "interaction_links": interaction_links,
        "edge_index_by_node": edge_index_by_node,
        "overview": {
            "node_ids": [str(n["id"]) for n in overview_nodes],
            "edge_indexes": overview_edges,
        },
        "paper_map": paper_map,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output_json),
                "overview_nodes": len(result["overview"]["node_ids"]),
                "overview_edges": len(result["overview"]["edge_indexes"]),
                "all_nodes": len(node_map),
                "all_edges": len(edges),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

