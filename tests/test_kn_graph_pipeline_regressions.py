from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kn_graph.config import Settings
from kn_graph.routers import pipeline as pipeline_router
from kn_graph.services.pipeline_service import PipelineService


class _FakePipelineService:
    def __init__(self) -> None:
        self.created_jobs: list[dict] = []
        self._settings = type("S", (), {"pipeline_executor": "celery"})()

    def health(self):
        return {"status": "ok", "executor": "inline"}

    def create_job(self, payload: dict):
        self.created_jobs.append(dict(payload))
        return dict(payload)

    def list_jobs(self, **_kwargs):
        return {"jobs": [], "total": 0, "page": 1, "page_size": 50}

    def get_job(self, _job_id: str):
        return None

    def get_result(self, _job_id: str):
        return None

    def cancel_job(self, _job_id: str):
        return {"error": "job_not_found"}

    def retry_job(self, _job_id: str):
        return None


class TestPipelineRouterRegressions(unittest.TestCase):
    def test_retry_missing_job_returns_404_instead_of_500(self) -> None:
        app = FastAPI()
        app.include_router(pipeline_router.create_router(_FakePipelineService()))
        client = TestClient(app)

        resp = client.post("/v1/jobs/job_missing/retry")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json().get("error"), "job_not_found")

    def test_batch_upload_keeps_created_job_payloads(self) -> None:
        fake = _FakePipelineService()
        app = FastAPI()
        app.include_router(pipeline_router.create_router(fake))
        client = TestClient(app)

        with tempfile.TemporaryDirectory() as tmp:
            original = pipeline_router._resolve_library_workspace
            pipeline_router._resolve_library_workspace = lambda _library_id: Path(tmp)
            try:
                resp = client.post(
                    "/v1/pipeline/parse-extract/batch",
                    files=[
                        ("files", ("a.pdf", b"%PDF-1.4\na", "application/pdf")),
                        ("files", ("b.pdf", b"%PDF-1.4\nb", "application/pdf")),
                    ],
                    data={"library_id": "lib_x"},
                )
            finally:
                pipeline_router._resolve_library_workspace = original

        self.assertEqual(resp.status_code, 202)
        payload = resp.json()
        accepted = payload.get("accepted") or []
        self.assertEqual(len(accepted), 2)
        self.assertTrue(all(isinstance(item, dict) and item.get("job_id") for item in accepted))


class TestPipelineServiceRegressions(unittest.TestCase):
    def test_postgres_dsn_does_not_silently_fallback_to_inmemory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = PipelineService(
                Settings(
                    data_dir=Path(tmp),
                    pipeline_job_store_dsn="postgresql://user:pass@127.0.0.1:5432/kn_graph",
                )
            )
            with self.assertRaises(RuntimeError):
                svc._ensure_store()


if __name__ == "__main__":
    unittest.main()
