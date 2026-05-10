from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "smj_pipeline" / "kn_mcp_server.py"
    spec = importlib.util.spec_from_file_location("kn_mcp_server_for_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tool_list_includes_graph_variable_concept_search():
    mod = _load_module()
    tools = mod._build_tools()
    names = [str(t.get("name", "")) for t in tools if isinstance(t, dict)]
    assert "graph_variable_concept_search" in names

    tool = next(t for t in tools if t.get("name") == "graph_variable_concept_search")
    schema = tool.get("inputSchema", {}) if isinstance(tool, dict) else {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    assert "query" in props
    assert "top_k" in props
    assert "library_id" in props
    assert schema.get("required") == ["query"]


def test_variable_concept_search_uses_default_top_k_and_returns_expected_shape(monkeypatch):
    mod = _load_module()
    state: dict[str, object] = {}

    class _FakeService:
        def __init__(self, workspace_path: str = "") -> None:
            state["workspace_path"] = workspace_path

        def query(self, library_id: str, query: str, top_k: int = 5):
            state["query_call"] = {"library_id": library_id, "query": query, "top_k": top_k}
            return [
                {
                    "id": "lib-1::paper-1::var_a",
                    "score": 0.91,
                    "library_id": library_id,
                    "paper_id": "paper-1",
                    "variable_name": "Var A",
                    "canonical_var_id": "var::a",
                    "concept_text": "definition a",
                }
            ]

        def expand_aliases(self, db_path: str, canonical_var_ids: list[str]):
            state["expand_aliases_call"] = {"db_path": db_path, "canonical_var_ids": canonical_var_ids}
            return {"var::a": ["Var A", "A"]}

    monkeypatch.setattr(mod, "_resolve_library_scope", lambda _base_url, _library_id="": (["lib-1"], "lib-1"))
    monkeypatch.setattr(
        mod,
        "_api_get_json",
        lambda _base_url, path: {"libraries": [{"library_id": "lib-1", "workspace_path": "D:/tmp/lib-1"}]}
        if path == "/literature/libraries"
        else {},
    )
    calls: list[str] = []
    monkeypatch.setattr(
        mod,
        "_handle_graph_variable_neighbors",
        lambda _base_url, _args: (
            calls.append(str(_args.get("variable_name", ""))),
            {
                "ok": True,
                "upstream": [{"variable_name": "Cause A", "relation": "positive"}],
                "downstream": [{"variable_name": "Outcome B", "relation": "positive"}],
            },
        )[1],
    )
    monkeypatch.setattr(mod, "VariableConceptIndexService", _FakeService)

    out = mod._handle_graph_variable_concept_search("http://127.0.0.1:8013", {"query": "definition"})
    assert out.get("ok") is True
    assert state["query_call"]["top_k"] == 5
    assert "matched_variables" in out
    assert "papers" in out
    assert "trace" in out
    mv = out["matched_variables"][0]
    assert isinstance(mv.get("cause_variables"), list)
    assert isinstance(mv.get("effect_variables"), list)
    assert mv["cause_variables"][0]["variable_name"] == "Cause A"
    assert mv["effect_variables"][0]["variable_name"] == "Outcome B"
    # exact-neighborhood should run for variable_name + alias expansion
    assert set(calls) >= {"Var A", "A"}


def test_variable_concept_search_allows_custom_top_k(monkeypatch):
    mod = _load_module()
    state: dict[str, object] = {}

    class _FakeService:
        def __init__(self, workspace_path: str = "") -> None:
            _ = workspace_path

        def query(self, library_id: str, query: str, top_k: int = 5):
            state["top_k"] = top_k
            return []

        def expand_aliases(self, db_path: str, canonical_var_ids: list[str]):
            _ = db_path, canonical_var_ids
            return {}

    monkeypatch.setattr(mod, "_resolve_library_scope", lambda _base_url, _library_id="": (["lib-1"], "lib-1"))
    monkeypatch.setattr(
        mod,
        "_api_get_json",
        lambda _base_url, path: {"libraries": [{"library_id": "lib-1", "workspace_path": "D:/tmp/lib-1"}]}
        if path == "/literature/libraries"
        else {},
    )
    monkeypatch.setattr(mod, "VariableConceptIndexService", _FakeService)

    _ = mod._handle_graph_variable_concept_search(
        "http://127.0.0.1:8013",
        {"query": "definition", "top_k": 9},
    )
    assert state.get("top_k") == 9
