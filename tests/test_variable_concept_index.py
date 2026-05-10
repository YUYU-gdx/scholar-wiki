from __future__ import annotations

import sqlite3
from pathlib import Path

import chromadb

from kn_graph.services.variable_concept_index import VariableConceptIndexService


def _init_workspace_db(workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = workspace / "kn_gragh.db"
    conn = sqlite3.connect(str(db_path))
    try:
        schema_path = Path(__file__).resolve().parents[1] / "src" / "kn_graph" / "services" / "schema.sql"
        conn.executescript(schema_path.read_text(encoding="utf-8"))

        conn.execute("INSERT INTO papers (paper_id, doi, title) VALUES (?, ?, ?)", ("paper-1", "10.1/test", "Paper One"))
        conn.execute(
            "INSERT INTO canonical_variables (canonical_var_id, canonical_name) VALUES (?, ?)",
            ("var::firm performance", "Firm Performance"),
        )
        conn.execute(
            "INSERT INTO canonical_variables (canonical_var_id, canonical_name) VALUES (?, ?)",
            ("var::supply chain resilience", "Supply Chain Resilience"),
        )

        conn.execute(
            """
            INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("var::firm performance", "FP", "fp", "model", "paper-1"),
        )
        conn.execute(
            """
            INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("var::firm performance", "Firm Perf", "firm-perf", "model", "paper-1"),
        )
        conn.execute(
            """
            INSERT INTO variable_aliases (canonical_var_id, alias_text, alias_norm, source, paper_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("var::supply chain resilience", "SCR", "scr", "model", "paper-1"),
        )

        conn.execute(
            """
            INSERT INTO variable_definitions (paper_id, variable_name, aliases_json, definition_text, measurement_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "paper-1",
                "Firm Performance",
                '["SHOULD_NOT_APPEAR"]',
                "Firm performance captures overall organizational outcomes.",
                "Measured by ROA and growth.",
            ),
        )
        conn.execute(
            """
            INSERT INTO variable_definitions (paper_id, variable_name, aliases_json, definition_text, measurement_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "paper-1",
                "Supply Chain Resilience",
                "[]",
                "Supply chain resilience reflects recovery capability after disruptions.",
                "Measured by disruption recovery speed.",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_upsert_and_query_returns_doc_level_hits(tmp_path):
    workspace = tmp_path / "workspace"
    db_path = _init_workspace_db(workspace)
    service = VariableConceptIndexService(workspace_path=str(workspace))

    result = service.upsert_paper_variable_concepts(
        library_id="lib_demo",
        paper_id="paper-1",
        db_path=str(db_path),
    )
    assert result["upserted"] == 2

    hits = service.query(library_id="lib_demo", query="recovery capability", top_k=5)
    assert hits
    matched = [h for h in hits if h.get("canonical_var_id") == "var::supply chain resilience"]
    assert matched
    assert matched[0]["paper_id"] == "paper-1"
    assert matched[0]["variable_name_norm"] == "supply_chain_resilience"


def test_expand_aliases_reads_only_canonical_and_alias_tables(tmp_path):
    workspace = tmp_path / "workspace"
    db_path = _init_workspace_db(workspace)
    service = VariableConceptIndexService(workspace_path=str(workspace))

    aliases = service.expand_aliases(
        db_path=str(db_path),
        canonical_var_ids=["var::firm performance"],
    )

    assert "var::firm performance" in aliases
    values = aliases["var::firm performance"]
    assert "Firm Performance" in values
    assert "FP" in values
    assert "Firm Perf" in values
    assert "SHOULD_NOT_APPEAR" not in values


def test_upsert_is_idempotent_no_duplicate_documents(tmp_path):
    workspace = tmp_path / "workspace"
    db_path = _init_workspace_db(workspace)
    service = VariableConceptIndexService(workspace_path=str(workspace))

    first = service.upsert_paper_variable_concepts(
        library_id="lib_demo",
        paper_id="paper-1",
        db_path=str(db_path),
    )
    second = service.upsert_paper_variable_concepts(
        library_id="lib_demo",
        paper_id="paper-1",
        db_path=str(db_path),
    )

    assert first["upserted"] == 2
    assert second["upserted"] == 0
    assert second["updated"] == 2

    persist_dir = workspace / "corpus" / "variables_concept_index"
    client = chromadb.PersistentClient(path=str(persist_dir))
    col = client.get_collection("variable_concepts_v1")
    rows = col.get(where={"library_id": "lib_demo"}, include=["metadatas"])
    assert len(rows.get("ids", [])) == 2


def _load_backfill_module():
    import importlib.util

    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "smj_pipeline" / "backfill_variable_concept_index.py"
    spec = importlib.util.spec_from_file_location("backfill_variable_concept_index_for_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backfill_script_library_id_outputs_summary_and_is_idempotent(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "workspace"
    _ = _init_workspace_db(workspace)
    mod = _load_backfill_module()

    monkeypatch.setattr(
        mod.lr_mod,
        "ensure_registry",
        lambda: {"default_library_id": "lib_demo", "libraries": [{"library_id": "lib_demo"}]},
    )
    monkeypatch.setattr(
        mod.lr_mod,
        "resolve_workspace_root",
        lambda _registry, library_id: str(workspace) if library_id == "lib_demo" else "",
    )

    rc1 = mod.main(["--library-id", "lib_demo"])
    out1 = capsys.readouterr().out.strip()
    payload1 = __import__("json").loads(out1)
    assert rc1 == 0
    assert payload1["libraries"]["lib_demo"] == {
        "processed": 1,
        "inserted": 2,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    rc2 = mod.main(["--library-id", "lib_demo"])
    out2 = capsys.readouterr().out.strip()
    payload2 = __import__("json").loads(out2)
    assert rc2 == 0
    assert payload2["libraries"]["lib_demo"] == {
        "processed": 1,
        "inserted": 0,
        "updated": 2,
        "skipped": 0,
        "errors": 0,
    }

    persist_dir = workspace / "corpus" / "variables_concept_index"
    client = chromadb.PersistentClient(path=str(persist_dir))
    col = client.get_collection("variable_concepts_v1")
    rows = col.get(where={"library_id": "lib_demo"}, include=["metadatas"])
    assert len(rows.get("ids", [])) == 2


def test_backfill_script_all_scopes_each_library_and_collects_errors(tmp_path, monkeypatch, capsys):
    workspace_ok = tmp_path / "lib_ok"
    _ = _init_workspace_db(workspace_ok)
    workspace_missing = tmp_path / "lib_missing_db"
    workspace_missing.mkdir(parents=True, exist_ok=True)

    mod = _load_backfill_module()
    registry_payload = {
        "default_library_id": "lib_ok",
        "libraries": [
            {"library_id": "lib_ok"},
            {"library_id": "lib_missing"},
        ],
    }
    monkeypatch.setattr(mod.lr_mod, "ensure_registry", lambda: registry_payload)
    monkeypatch.setattr(
        mod.lr_mod,
        "resolve_workspace_root",
        lambda _registry, library_id: (
            str(workspace_ok)
            if library_id == "lib_ok"
            else str(workspace_missing)
            if library_id == "lib_missing"
            else ""
        ),
    )

    rc = mod.main(["--all"])
    out = capsys.readouterr().out.strip()
    payload = __import__("json").loads(out)
    assert rc == 0
    assert payload["libraries"]["lib_ok"] == {
        "processed": 1,
        "inserted": 2,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert payload["libraries"]["lib_missing"] == {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 1,
    }
