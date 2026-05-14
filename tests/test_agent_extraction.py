"""Tests for _run_agent_extraction in isolation."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class TestAgentExtraction:
    """Test _run_agent_extraction function."""

    def setup_method(self) -> None:
        """Ensure _pipeline_settings is initialized so the function does not fail
        even if a test path reaches code that reads the global."""
        from kn_graph.config import Settings
        from kn_graph.services.pipeline_runtime import init_pipeline_settings

        init_pipeline_settings(Settings())

    def _mock_store(self) -> MagicMock:
        store = MagicMock()
        store.get_job.return_value = {
            "status": "running",
            "stage": "parse_pdf",
            "requested_cancel": False,
        }
        return store

    def _make_options(self, **overrides: str) -> dict[str, str]:
        opts: dict[str, str] = {
            "extraction_mode": "agent",
            "pipeline_agent_backend": "codex",
            "pipeline_agent_provider": "deepseek",
            "library_id": "test_lib",
            "paper_id": "test_paper_001",
            "doi": "10.1234/test",
        }
        opts.update(overrides)
        return opts

    def test_missing_html_path_raises(self) -> None:
        """Agent extraction raises when html_path does not exist."""
        from kn_graph.services.pipeline_runtime import _run_agent_extraction

        parse_meta: dict[str, str] = {"html_path": "/nonexistent/path.html"}
        run_dir = Path(tempfile.mkdtemp())
        store = self._mock_store()
        options = self._make_options()

        with pytest.raises(RuntimeError, match="missing_html_for_extraction"):
            _run_agent_extraction("job_1", parse_meta, run_dir, store, options)

    def test_missing_library_id_raises(self) -> None:
        """Agent extraction raises when library_id is missing."""
        from kn_graph.services.pipeline_runtime import _run_agent_extraction

        f = tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False)
        try:
            f.write("<html><body>Test paper</body></html>")
            f.close()
            html_path = f.name

            parse_meta: dict[str, str] = {"html_path": html_path}
            run_dir = Path(tempfile.mkdtemp())
            store = self._mock_store()
            options = self._make_options(library_id="")

            with pytest.raises(RuntimeError, match="library_id_required"):
                _run_agent_extraction("job_1", parse_meta, run_dir, store, options)
        finally:
            os.unlink(html_path)

    def test_cancel_requested_during_agent_extraction(self) -> None:
        """Agent extraction raises job_cancelled when cancel is requested."""
        import shutil

        from kn_graph.services.pipeline_runtime import _run_agent_extraction

        ws = Path(tempfile.mkdtemp())
        try:
            (ws / "corpus" / "papers").mkdir(parents=True)
            html_path = ws / "corpus" / "papers" / "test_paper" / "paper.md"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text("# Test Paper\n\nContent.", encoding="utf-8")

            parse_meta: dict[str, str] = {"html_path": str(html_path)}
            run_dir = Path(tempfile.mkdtemp())
            store = self._mock_store()
            store.get_job.return_value = {
                "status": "running",
                "stage": "parse_pdf",
                "requested_cancel": True,
            }
            options = self._make_options()

            with pytest.raises(RuntimeError, match="job_cancelled"):
                _run_agent_extraction("job_1", parse_meta, run_dir, store, options)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_missing_workspace_raises(self) -> None:
        """Agent extraction raises when workspace cannot be resolved from html_path."""
        import shutil

        from kn_graph.services.pipeline_runtime import _run_agent_extraction

        # Create an HTML file NOT inside a corpus/papers structure
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            html_path = tmp_dir / "standalone.html"
            html_path.write_text("<html><body>Test</body></html>", encoding="utf-8")

            parse_meta: dict[str, str] = {"html_path": str(html_path)}
            run_dir = Path(tempfile.mkdtemp())
            store = self._mock_store()
            options = self._make_options()

            with pytest.raises(RuntimeError, match="cannot_resolve_workspace"):
                _run_agent_extraction("job_1", parse_meta, run_dir, store, options)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_missing_extract_result_json_treated_as_not_extractable(self) -> None:
        """If agent writes no extract_result.json, treat as not extractable and continue."""
        import shutil

        from kn_graph.services.pipeline_runtime import _run_agent_extraction

        ws = Path(tempfile.mkdtemp())
        run_dir = Path(tempfile.mkdtemp())
        try:
            paper_dir = ws / "corpus" / "papers" / "paper_a"
            paper_dir.mkdir(parents=True, exist_ok=True)
            md_path = paper_dir / "paper.md"
            html_path = paper_dir / "paper.html"
            md_path.write_text("# Paper A\n\nBody.", encoding="utf-8")
            html_path.write_text("<html><body>Paper A</body></html>", encoding="utf-8")

            parse_meta: dict[str, str] = {
                "markdown_path": str(md_path),
                "html_path": str(html_path),
            }
            store = self._mock_store()
            options = self._make_options(_workspace_path=str(ws))

            fake_runner = MagicMock()
            fake_runner.run_turn.return_value = {"ok": True}
            fake_factory = MagicMock()
            fake_factory.build.return_value = fake_runner

            with (
                patch("kn_graph.services.agent_workspace_guard.ensure_agent_workspace_minimal_config", return_value=None),
                patch("kn_graph.services.codex_library_config.bootstrap_workspace_project_skills", return_value=None),
                patch("kn_graph.services.agent_runner.AgentRunnerFactory", return_value=fake_factory),
            ):
                payload = _run_agent_extraction("job_1", parse_meta, run_dir, store, options)

            assert payload["summary"]["class_a_used"] == 0
            assert payload["summary"]["class_b_skipped"] == 1
            assert payload["metrics"]["extractable_rate"] == 0.0
            assert "not_extractable_reason" in payload
            assert (run_dir / "extract" / "extract_result.json").exists()
            assert not (run_dir / "extract" / "raw_llm_outputs.jsonl").exists()
        finally:
            shutil.rmtree(ws, ignore_errors=True)
            shutil.rmtree(run_dir, ignore_errors=True)
