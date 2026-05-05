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
