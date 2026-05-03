"""
End-to-end pipeline test: LLM output (new format) -> extract -> export -> graph views.
Runs without external dependencies (no PDF parser, no LLM, no DB).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

def main() -> int:
    # ---- Step 1: Simulate LLM output in the NEW data model format ----
    paper_id = "test-paper-001"
    doi = "10.1002/test.001"

    raw_llm_output = {
        "extractability_status": "yes",
        "paper_type": "quantitative_empirical",
        "extractability_reason": "has OLS regression with hypothesis testing",
        "extractability_evidence_section": "Methods",
        "variable_definitions": [
            {
                "variable_name": "strategic flexibility",
                "definition": "the ability to adapt strategies",
                "measurement": "5-item Likert scale adapted from Sanchez (1995)",
                "aliases": ["flexibility", "strategic adaptability"]
            },
            {
                "variable_name": "firm performance",
                "definition": "financial performance measured by ROA",
                "measurement": "Return on Assets from Compustat",
                "aliases": ["performance", "ROA"]
            },
            {
                "variable_name": "environmental dynamism",
                "definition": "rate and unpredictability of environmental change",
                "measurement": "4-item scale from Miller & Friesen (1982)",
                "aliases": ["dynamism", "environmental turbulence"]
            },
            {
                "variable_name": "R&D intensity",
                "definition": "R&D expenditure divided by total sales",
                "measurement": "R&D/Sales ratio",
                "aliases": []
            },
            {
                "variable_name": "marketing capability",
                "definition": "firm's ability to market products effectively",
                "measurement": "survey scale",
                "aliases": []
            },
            {
                "variable_name": "new product success",
                "definition": "success of new product introductions",
                "measurement": "market performance of new products",
                "aliases": ["NPS", "innovation success"]
            }
        ],
        "direct_effects": [
            {
                "source": "strategic flexibility",
                "target": "firm performance",
                "effect_form": "positive",
                "theory_name": "dynamic capabilities",
                "evidence_text": "H1: Strategic flexibility positively affects firm performance (beta=0.34, p<0.01)",
                "verification": "supported"
            },
            {
                "source": "strategic flexibility",
                "target": "firm performance",
                "effect_form": "nonlinear",
                "theory_name": "dynamic capabilities",
                "evidence_text": "H2: The effect of strategic flexibility on firm performance exhibits an inverted-U shape (p<0.05)",
                "verification": "supported"
            },
            {
                "source": "R&D intensity",
                "target": "firm performance",
                "effect_form": "positive",
                "theory_name": "resource based view",
                "evidence_text": "H3: R&D intensity positively affects firm performance",
                "verification": "mixed"
            }
        ],
        "moderations": [
            {
                "moderator": "environmental dynamism",
                "source": "strategic flexibility",
                "target": "firm performance",
                "effect_form": "positive",
                "theory_name": "contingency theory",
                "evidence_text": "H4: Environmental dynamism positively moderates the effect of strategic flexibility on firm performance (interaction beta=0.21, p<0.01)",
                "verification": "supported"
            },
            {
                "moderator": "environmental dynamism",
                "source": "R&D intensity",
                "target": "firm performance",
                "effect_form": "negative",
                "theory_name": "contingency theory",
                "evidence_text": "H5: Environmental dynamism negatively moderates the effect of R&D intensity on firm performance (interaction beta=-0.15, p<0.05)",
                "verification": "supported"
            }
        ],
        "interactions": [
            {
                "inputs": ["R&D intensity", "marketing capability"],
                "output": "new product success",
                "effect_form": "positive",
                "theory_name": "complementarity theory",
                "evidence_text": "H6: R&D intensity and marketing capability jointly enhance new product success",
                "verification": "supported"
            }
        ]
    }

    print("[1/5] Synthetic LLM output prepared (new data model format)")
    print(f"      {len(raw_llm_output['direct_effects'])} direct effects, "
          f"{len(raw_llm_output['moderations'])} moderations, "
          f"{len(raw_llm_output['interactions'])} interactions")

    # ---- Step 2: Parse via extractor ----
    import importlib.util
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline"
    extractor_path = scripts_dir / "extraction" / "extractor.py"

    spec = importlib.util.spec_from_file_location("e2e_extractor", extractor_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    raw_json = json.dumps(raw_llm_output, ensure_ascii=False)
    bundle = mod.parse_extraction_response(raw_json)

    print("[2/5] Extractor parsed successfully")
    assert bundle.extractability_status == "yes", "extractability_status mismatch"
    assert len(bundle.direct_effects) == 3, f"direct_effects count mismatch: {len(bundle.direct_effects)}"
    assert len(bundle.moderations) == 2, f"moderations count mismatch: {len(bundle.moderations)}"
    assert len(bundle.interactions) == 1, f"interactions count mismatch: {len(bundle.interactions)}"
    assert len(bundle.variable_definitions) == 6, f"variable_defs count mismatch: {len(bundle.variable_definitions)}"

    # Check field names in normalized output
    de = bundle.direct_effects[0]
    assert "source" in de and "target" in de and "effect_form" in de, "direct_effects missing new fields"
    assert "theory_name" in de and "evidence_text" in de, "direct_effects missing new fields"
    assert "from" not in de, "old 'from' field leaked into direct_effects"
    assert "direction" not in de, "old 'direction' field leaked into direct_effects"
    assert "relation_form" not in de, "old 'relation_form' field leaked into direct_effects"

    mod_row = bundle.moderations[0]
    assert "moderator" in mod_row and "source" in mod_row and "target" in mod_row, "moderation missing flat fields"
    assert "effect_form" in mod_row, "moderation missing effect_form"
    assert "moderated_effects" not in mod_row, "old nested moderated_effects leaked"

    inter = bundle.interactions[0]
    assert "inputs" in inter and "output" in inter, "interaction missing fields"
    assert "effect_form" in inter and "evidence_text" in inter, "interaction missing new fields"
    assert "type" not in inter, "old 'type' field leaked into interactions"
    assert "effect" not in inter, "old 'effect' field leaked into interactions"

    vd = bundle.variable_definitions[0]
    assert "variable_name" in vd, "variable_definitions missing variable_name"
    assert "variable" not in vd or vd.get("variable_name"), "old 'variable' field should not be primary"
    assert "measurement" in vd, "variable_definitions missing measurement"

    print("      All field name assertions passed")

    # ---- Step 3: Build raw_output.jsonl and export ----
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)

        # Write raw_llm_outputs.jsonl
        raw_jsonl_path = tmpd / "raw_llm_outputs.jsonl"
        with raw_jsonl_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({
                "paper_id": paper_id,
                "doi": doi,
                "status": "ok",
                "raw_response": raw_json,
                "offline_html_path": "",
                "article_url": "",
                "publication_date": "2024-01-15",
                "publication_year": 2024,
                "paper_citation_count": 42,
                "paper_domains": ["strategy", "innovation"],
            }, ensure_ascii=False))
            f.write("\n")

        # Run export_frontend_artifact
        export_spec = importlib.util.spec_from_file_location(
            "e2e_export", scripts_dir / "export_frontend_artifact.py"
        )
        export_mod = importlib.util.module_from_spec(export_spec)
        sys.modules[export_spec.name] = export_mod
        export_spec.loader.exec_module(export_mod)

        artifact_path = tmpd / "frontend_artifact.json"
        result = export_mod.run_export(input_json=raw_jsonl_path, output_json=artifact_path)
        assert result is not None, "export_frontend_artifact returned None"
        assert result.exists(), "artifact file not created"

        print("[3/5] export_frontend_artifact completed")

        # ---- Step 4: Build graph views ----
        build_spec = importlib.util.spec_from_file_location(
            "e2e_build", scripts_dir / "build_graph_views.py"
        )
        build_mod = importlib.util.module_from_spec(build_spec)
        sys.modules[build_spec.name] = build_mod
        build_spec.loader.exec_module(build_mod)

        views_path = tmpd / "graph_views.json"
        build_result = build_mod.run_build(artifact_json=artifact_path, output_json=views_path)
        assert build_result is not None, "build_graph_views returned None"
        assert build_result.exists(), "graph_views file not created"

        print("[4/5] build_graph_views completed")

        # ---- Step 5: Validate artifact contents ----
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        views = json.loads(views_path.read_text(encoding="utf-8"))

        # Check meta
        assert artifact["meta"]["success_rows"] == 1
        assert artifact["meta"]["node_count"] > 0
        assert artifact["meta"]["edge_count"] >= 3
        assert artifact["meta"]["interaction_count"] == 1

        # Check edges have new field names
        for edge in artifact["edges"]:
            assert "effect_form" in edge, f"edge missing effect_form"
            assert "evidence_text" in edge, f"edge missing evidence_text"
            assert "theory_name" in edge, f"edge missing theory_name"
            assert "evidence_section" not in edge, f"old evidence_section leaked into edge"
            assert "direction" not in edge, f"old direction leaked into edge"

        # Check moderation links
        for mod_link in artifact["moderation_links"]:
            assert "effect_form" in mod_link
            assert "evidence_text" in mod_link
            assert "theory_name" in mod_link
            assert "moderator_node_id" in mod_link, "moderation link missing moderator_node_id"

        # Check interaction links
        for int_link in artifact["interaction_links"]:
            assert "effect_form" in int_link
            assert "evidence_text" in int_link
            assert "theory_name" in int_link
            assert "input_node_ids" in int_link
            assert "output_node_id" in int_link

        # Check paper payload
        paper = artifact["papers"][0]
        assert "direct_effects" in paper, "paper missing direct_effects"
        assert "main_effects" not in paper, "old main_effects leaked into paper"
        assert "interactions" in paper
        assert "variable_definitions" in paper
        vd_first = paper["variable_definitions"][0]
        assert "variable_name" in vd_first or "variable" in vd_first
        assert "measurement" in vd_first, "variable_def missing measurement"
        assert "context_variables" not in paper, "old context_variables leaked"
        assert "operationalization" not in paper, "old operationalization leaked"

        # Check graph views
        assert "nodes" in views and isinstance(views["nodes"], dict)
        assert "edges" in views
        assert "edge_index_by_node" in views
        assert "overview" in views
        assert "paper_map" in views
        assert len(views["paper_map"]) > 0

        print("[5/5] Artifact & graph views validation passed")
        print()
        print("=" * 60)
        print("END-TO-END PIPELINE TEST PASSED")
        print("=" * 60)
        print(f"  Nodes: {artifact['meta']['node_count']}")
        print(f"  Edges: {artifact['meta']['edge_count']}")
        print(f"  Moderation links: {len(artifact['moderation_links'])}")
        print(f"  Interaction links: {len(artifact['interaction_links'])}")
        print(f"  Papers: {artifact['meta']['paper_count']}")
        print(f"  Overview nodes: {len(views['overview']['node_ids'])}")
        print(f"  Overview edges: {len(views['overview']['edge_indexes'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
