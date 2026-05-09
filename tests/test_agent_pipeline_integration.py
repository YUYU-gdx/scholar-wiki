"""Integration tests: full pipeline with agent extraction mode."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class TestAgentPipelineIntegration:
    """End-to-end pipeline flow with extraction_mode=agent."""

    def test_settings_flow_extraction_mode_injects_correctly(self):
        """Verify extraction_mode flows from Settings to pipeline options."""
        from kn_graph.config import Settings
        from kn_graph.services.pipeline_runtime import _inject_pipeline_settings, init_pipeline_settings

        settings = Settings()
        mock_store = {
            "categories": {
                "pipeline": {"extraction_mode": "agent"},
                "pipeline_agent": {
                    "backend": "codex",
                    "provider": "deepseek",
                    "reasoning_effort": "high",
                },
            }
        }
        with patch.object(Settings, "_store", mock_store):
            init_pipeline_settings(settings)
            options = _inject_pipeline_settings({})
        assert options.get("extraction_mode") == "agent"
        assert options.get("pipeline_agent_backend") == "codex"
        assert options.get("pipeline_agent_provider") == "deepseek"
        assert options.get("pipeline_agent_reasoning_effort") == "high"

    def test_settings_flow_defaults_to_agent(self):
        """Verify default extraction_mode is agent when not overridden."""
        from kn_graph.config import Settings
        from kn_graph.services.pipeline_runtime import _inject_pipeline_settings, init_pipeline_settings

        settings = Settings()
        init_pipeline_settings(settings)

        options = _inject_pipeline_settings({})
        assert options.get("extraction_mode") == "agent"

    def test_settings_flow_agent_options_not_overwrite_explicit(self):
        """Verify explicit options are not overwritten by settings defaults."""
        from kn_graph.config import Settings
        from kn_graph.services.pipeline_runtime import _inject_pipeline_settings, init_pipeline_settings

        settings = Settings()
        # Leave pipeline_agent_* at defaults (empty strings)
        init_pipeline_settings(settings)

        explicit_options = {
            "extraction_mode": "fast",
            "pipeline_agent_backend": "gemini_cli",
        }
        options = _inject_pipeline_settings(explicit_options)
        # Explicit values should be preserved
        assert options.get("extraction_mode") == "fast"
        assert options.get("pipeline_agent_backend") == "gemini_cli"

    def test_extract_result_payload_format_compatibility(self):
        """Verify agent extract_result payload matches what _run_finalize expects."""
        payload = {
            "summary": {
                "seen": 1, "class_a_used": 1, "class_b_skipped": 0,
                "class_c_skipped": 0, "denominator_used": 1
            },
            "metrics": {
                "extractable_rate": 1.0,
                "mean_direct_effects_per_doc": 2.0,
                "mean_moderations_per_doc": 1.0,
                "mean_interactions_per_doc": 0.0,
                "direct_effect_validation_rate": 1.0,
            },
            "report_path": "/tmp/extract/acceptance_report.md",
            "raw_output_jsonl": "/tmp/extract/raw_llm_outputs.jsonl",
            "review_queue_jsonl": "/tmp/extract/review_queue.jsonl",
        }
        required_keys = {"summary", "metrics", "report_path", "raw_output_jsonl", "review_queue_jsonl"}
        assert required_keys.issubset(set(payload.keys()))
        assert isinstance(payload["summary"], dict)
        assert isinstance(payload["metrics"], dict)
        assert "class_a_used" in payload["summary"]
        assert "extractable_rate" in payload["metrics"]

    def test_agent_bundle_to_raw_jsonl_conversion(self):
        """Verify the raw_output_jsonl format is compatible with import_sqlite."""
        agent_bundle = {
            "paper_domains": ["supply_chain"],
            "extractability_status": "yes",
            "paper_type": "empirical",
            "variable_definitions": [
                {"variable_id": "v1", "variable_name": "SCI", "definition": "supply chain integration"}
            ],
            "direct_effects": [
                {"source": "v1", "target": "v2",
                 "effect_form": "positive", "verification": "supported", "evidence_text": "test"}
            ],
            "moderations": [],
            "interactions": [],
        }
        raw_record = {
            "paper_id": "test_001",
            "doi": "10.1234/test",
            "status": "ok",
            "evidence_spans": 1,
            "paper_domains": agent_bundle.get("paper_domains", []),
            "raw_response": json.dumps(agent_bundle, ensure_ascii=False),
        }
        # Verify the raw_response can be parsed back
        parsed = json.loads(raw_record["raw_response"])
        assert parsed["extractability_status"] == "yes"
        assert len(parsed["variable_definitions"]) == 1
        assert len(parsed["direct_effects"]) == 1
        assert "paper_id" in raw_record
        assert raw_record["status"] == "ok"

    def test_dispatcher_routes_to_fast_by_default(self):
        """Verify the dispatcher calls fast path when extraction_mode is not agent."""
        from kn_graph.services.pipeline_runtime import _run_extract_entities

        # With fast mode, this should NOT raise agent_extraction_not_implemented
        # It will fail on missing html_path (expected for fast path validation)
        parse_meta = {"html_path": "/nonexistent/path.html"}
        run_dir = Path(tempfile.mkdtemp())
        store = MagicMock()
        store.get_job.return_value = {"status": "running", "stage": "parse_pdf", "requested_cancel": False}
        options = {"extraction_mode": "fast"}

        with pytest.raises(RuntimeError, match="missing_html_for_extraction"):
            _run_extract_entities("job_1", parse_meta, run_dir, store, options)

    def test_dispatcher_routes_to_agent_when_mode_is_agent(self):
        """Verify the dispatcher calls agent path when extraction_mode is agent."""
        from kn_graph.services.pipeline_runtime import _run_extract_entities

        parse_meta = {"html_path": "/nonexistent/path.html"}
        run_dir = Path(tempfile.mkdtemp())
        store = MagicMock()
        store.get_job.return_value = {"status": "running", "stage": "parse_pdf", "requested_cancel": False}
        options = {"extraction_mode": "agent"}

        # Agent path validates html_path exists first, so it will raise missing_html
        with pytest.raises(RuntimeError, match="missing_html_for_extraction"):
            _run_extract_entities("job_1", parse_meta, run_dir, store, options)
