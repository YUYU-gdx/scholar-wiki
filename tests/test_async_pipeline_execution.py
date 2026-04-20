from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import fitz  # type: ignore


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "serve_async_pipeline_api.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_serve_async_pipeline_api_exec", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

InMemoryJobStore = _MOD.InMemoryJobStore
execute_pipeline = _MOD.execute_pipeline


class _FakeRunSummary:
    def to_dict(self) -> dict[str, int]:
        return {"seen": 1, "class_a_used": 1, "class_b_skipped": 0, "class_c_skipped": 0, "denominator_used": 1}


class _FakeArtifacts:
    def __init__(self) -> None:
        self.summary = _FakeRunSummary()
        self.metrics = {"extractable_rate": 1.0}
        self.report_markdown = "# report"


class _FakeRunModule:
    class NullLLMClient:
        pass

    class ZhipuChatCompletionsClient:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

    class NvidiaChatCompletionsClient:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

    @staticmethod
    def run(*args, **kwargs):
        _ = args, kwargs
        return _FakeArtifacts()


class AsyncPipelineExecutionTest(unittest.TestCase):
    @staticmethod
    def _write_test_pdf(path: Path) -> None:
        doc = fitz.open()
        doc.new_page(width=100, height=100)
        doc.save(str(path))
        doc.close()

    def test_execute_pipeline_completes_and_writes_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            input_pdf = tmp / "in.pdf"
            self._write_test_pdf(input_pdf)
            parse_dir = tmp / "runs" / "job_x" / "parse"
            parse_dir.mkdir(parents=True, exist_ok=True)
            html_path = parse_dir / "parsed.html"
            html_path.write_text("<html><body>ok</body></html>", encoding="utf-8")

            store = InMemoryJobStore()
            now = _MOD._now_iso()
            store.create_job(
                {
                    "job_id": "job_x",
                    "status": "queued",
                    "stage": "accepted",
                    "progress": 0,
                    "error_code": "",
                    "error_detail": "",
                    "input_path": str(input_pdf),
                    "output_path": "",
                    "options_json": "{}",
                    "result_json": "{}",
                    "requested_cancel": False,
                    "idempotency_key": "",
                    "last_event": "accepted",
                    "created_at": now,
                    "updated_at": now,
                }
            )

            fake_parse_meta = {
                "markdown_path": str(parse_dir / "parsed.md"),
                "html_path": str(html_path),
                "zip_path": str(parse_dir / "mineru.zip"),
                "page_count": 1,
                "batch_id": "batch_test",
            }
            with (
                patch.object(_MOD, "_run_parse_pdf", return_value=fake_parse_meta),
                patch.object(_MOD, "_maybe_load_run_extraction_mvp", return_value=_FakeRunModule()),
            ):
                execute_pipeline(store, "job_x", str(input_pdf), {}, tmp / "runs")

            row = store.get_job("job_x")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "completed")
            result_path = Path(str(row["output_path"]))
            self.assertTrue(result_path.exists())
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["job_id"], "job_x")
            self.assertIn("parse", payload)
            self.assertIn("extract", payload)

    def test_execute_pipeline_respects_cancel_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            input_pdf = tmp / "cancel.pdf"
            self._write_test_pdf(input_pdf)

            store = InMemoryJobStore()
            now = _MOD._now_iso()
            store.create_job(
                {
                    "job_id": "job_cancel",
                    "status": "queued",
                    "stage": "accepted",
                    "progress": 0,
                    "error_code": "",
                    "error_detail": "",
                    "input_path": str(input_pdf),
                    "output_path": "",
                    "options_json": "{}",
                    "result_json": "{}",
                    "requested_cancel": True,
                    "idempotency_key": "",
                    "last_event": "accepted",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            execute_pipeline(store, "job_cancel", str(input_pdf), {}, tmp / "runs")
            row = store.get_job("job_cancel")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
