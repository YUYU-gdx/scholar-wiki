import sqlite3
from pathlib import Path

from kn_graph.services.graph_builder import _build_artifact_from_sqlite
from kn_graph.services.graph_builder import _canonical_var_id as graph_canonical_var_id
from kn_graph.services.sqlite_repo import _canonical_var_id as repo_canonical_var_id


def _init_schema(db_path: Path) -> None:
    schema = Path("src/kn_graph/services/schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def test_canonical_variable_ids_are_case_insensitive() -> None:
    assert repo_canonical_var_id("AI Washing") == repo_canonical_var_id("AI washing")
    assert graph_canonical_var_id("AI Washing") == graph_canonical_var_id("AI washing")


def test_graph_builder_collapses_legacy_case_variant_canonical_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "case_variants.db"
    _init_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO papers (paper_id, title, publication_year) VALUES (?, ?, ?)", ("p1", "Paper 1", 2026))
        conn.execute("INSERT INTO papers (paper_id, title, publication_year) VALUES (?, ?, ?)", ("p2", "Paper 2", 2026))
        conn.execute(
            """
            INSERT INTO direct_effects (
              paper_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id,
              effect_form, verification, evidence_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p1", "AI Washing", "Trust", "var::AI Washing", "var::Trust", "negative", "supported", "e1"),
        )
        conn.execute(
            """
            INSERT INTO direct_effects (
              paper_id, source_var, target_var, source_canonical_var_id, target_canonical_var_id,
              effect_form, verification, evidence_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p2", "AI washing", "Trust", "var::AI washing", "var::Trust", "negative", "supported", "e2"),
        )
        conn.commit()
    finally:
        conn.close()

    artifact = _build_artifact_from_sqlite(db_path)
    nodes = [n for n in artifact["nodes"] if str(n.get("label", "")).casefold() == "ai washing"]
    assert len(nodes) == 1

    source_ids = {e["source"] for e in artifact["edges"] if str(e.get("source_name_local", "")).casefold() == "ai washing"}
    assert source_ids == {nodes[0]["id"]}
