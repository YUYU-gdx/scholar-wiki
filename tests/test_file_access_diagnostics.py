from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kn_graph.routers import literature as literature_router
from kn_graph.services.file_access_diagnostics import (
    append_file_access_diagnostics,
    build_import_path_diagnostics,
)


class TestFileAccessDiagnostics(unittest.TestCase):
    def test_windows_access_message_gets_vm_path_hints(self) -> None:
        detail = append_file_access_diagnostics(
            "[WinError 5] Windows cannot access the specified device, path, or file",
            source_path=r"\\VBOXSVR\share\paper.pdf",
        )

        self.assertIn("File access diagnostics", detail)
        self.assertIn(r"\\VBOXSVR\share\paper.pdf", detail)
        self.assertIn("Test-Path -LiteralPath", detail)
        self.assertIn("VM", detail)
        self.assertIn("shared", detail)

    def test_unrelated_errors_are_not_changed(self) -> None:
        detail = "mineru_parse_failed:bad response"

        self.assertEqual(detail, append_file_access_diagnostics(detail))

    def test_import_path_diagnostics_probe_key_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            workspace = data_dir / "libraries" / "workspaces" / "lib"
            workspace.mkdir(parents=True)

            payload = build_import_path_diagnostics(
                data_dir=data_dir,
                workspaces_dir=data_dir / "libraries" / "workspaces",
                library_id="lib",
                workspace_path=workspace,
                input_path=workspace / "missing.pdf",
            )

        self.assertEqual(payload["kind"], "import_path_diagnostics")
        self.assertEqual(payload["library_id"], "lib")
        self.assertTrue(payload["paths"]["workspace_path"]["exists"])
        self.assertFalse(payload["paths"]["input_path"]["exists"])


class TestZoteroImportDiagnostics(unittest.TestCase):
    def test_inaccessible_zotero_pdf_is_reported_in_import_response(self) -> None:
        class _LiteratureService:
            _settings = type(
                "S",
                (),
                {
                    "data_dir": Path("."),
                    "workspaces_dir": Path("."),
                    "pipeline_runs_root": Path("runs"),
                },
            )()

        class _PipelineService:
            _store = object()

            def create_job(self, payload: dict) -> dict:
                raise AssertionError("inaccessible PDFs should not create jobs")

        app = FastAPI()
        app.include_router(literature_router.create_router(_LiteratureService(), _PipelineService()))
        client = TestClient(app)

        with patch.object(literature_router, "resolve_library_workspace", return_value=Path(".")), patch.object(
            literature_router,
            "get_zotero_items_batch",
            return_value=[
                {
                    "item_id": 42,
                    "metadata": {"title": "Paper"},
                    "pdf_paths": [
                        {
                            "resolved_path": r"\\VBOXSVR\share\paper.pdf",
                            "file_exists": False,
                        }
                    ],
                }
            ],
        ):
            resp = client.post(
                "/literature/zotero/import",
                json={"data_dir": "C:\\Zotero", "library_id": "lib", "item_ids": [42]},
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("count"), 0)
        skipped = payload.get("skipped") or []
        self.assertEqual(len(skipped), 1)
        self.assertIn("File access diagnostics", skipped[0].get("detail", ""))


if __name__ == "__main__":
    unittest.main()
