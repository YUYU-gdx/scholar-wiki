from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "serve_async_pipeline_api.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_serve_async_pipeline_api", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

create_app = _MOD.create_app
InMemoryJobStore = _MOD.InMemoryJobStore


def _noop_dispatch(_ctx, _job_id, _input_path, _options) -> None:
    return


class AsyncPipelineApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryJobStore()
        app = create_app(job_store=self.store, run_pipeline_fn=_noop_dispatch)
        self.client = TestClient(app)

    def test_upload_pdf_returns_202_with_job_links(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("sample.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"options": json.dumps({"llm_provider": "zhipu"}, ensure_ascii=False)},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn("job_id", payload)
        self.assertEqual(payload["status"], "queued")
        self.assertTrue(str(payload.get("sse_url", "")).startswith("/v1/jobs/"))
        self.assertTrue(str(payload.get("result_url", "")).startswith("/v1/jobs/"))

    def test_invalid_options_returns_400(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("sample.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"options": "{bad json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("error"), "invalid_options_json")

    def test_non_pdf_upload_returns_400(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("sample.txt", b"hello", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_job_marks_cancel_requested(self) -> None:
        create_resp = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("cancel.pdf", b"%PDF-1.4\nfake", "application/pdf")},
        )
        job_id = create_resp.json()["job_id"]
        cancel_resp = self.client.post(f"/v1/jobs/{job_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        payload = cancel_resp.json()
        self.assertEqual(payload["job_id"], job_id)
        self.assertTrue(payload["cancel_requested"])

    def test_get_job_result_returns_404_before_completion(self) -> None:
        create_resp = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("result.pdf", b"%PDF-1.4\nfake", "application/pdf")},
        )
        job_id = create_resp.json()["job_id"]
        result_resp = self.client.get(f"/v1/jobs/{job_id}/result")
        self.assertIn(result_resp.status_code, (200, 404))


if __name__ == "__main__":
    unittest.main()
