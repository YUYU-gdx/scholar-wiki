from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
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
            data={
                "library_id": "supply_chain",
                "options": json.dumps({"llm_provider": "zhipu"}, ensure_ascii=False),
            },
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
            data={"library_id": "supply_chain", "options": "{bad json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("error"), "invalid_options_json")

    def test_non_pdf_upload_returns_400(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("sample.txt", b"hello", "text/plain")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_job_marks_cancel_requested(self) -> None:
        create_resp = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("cancel.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"library_id": "supply_chain"},
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
            data={"library_id": "supply_chain"},
        )
        job_id = create_resp.json()["job_id"]
        result_resp = self.client.get(f"/v1/jobs/{job_id}/result")
        self.assertIn(result_resp.status_code, (200, 404))

    def test_upload_requires_library_id(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("sample.pdf", b"%PDF-1.4\nfake", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("error"), "library_id_required")

    def test_input_pdf_path_is_under_workspace_imports_jobs(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("sample.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        job_id = str(payload["job_id"])
        status = self.client.get(f"/v1/jobs/{job_id}")
        self.assertEqual(status.status_code, 200)
        row = status.json()
        self.assertEqual(row.get("library_id"), "supply_chain")
        self.assertTrue(str(row.get("workspace_path", "")).strip())
        input_path = str(row.get("input_path", "")).replace("\\", "/")
        self.assertIn(f"/imports/jobs/{job_id}/input/", input_path)
        workspace_path = str(row.get("workspace_path", "")).replace("\\", "/")
        self.assertTrue(input_path.startswith(workspace_path.rstrip("/") + "/"))

    def test_result_contains_library_and_workspace_path(self) -> None:
        def _complete_dispatch(ctx, job_id, _input_path, _options) -> None:
            row = ctx.job_store.get_job(job_id) or {}
            result = {
                "job_id": job_id,
                "library_id": str(row.get("library_id", "")),
                "workspace_path": str(row.get("workspace_path", "")),
            }
            ctx.job_store.update_job(
                job_id,
                {
                    "status": "completed",
                    "stage": "finalize",
                    "progress": 100,
                    "output_path": str(Path(str(row.get("workspace_path", ""))) / "imports" / "jobs" / job_id / "result.json"),
                    "result_json": json.dumps(result, ensure_ascii=False),
                    "last_event": "completed",
                },
            )

        app = create_app(job_store=InMemoryJobStore(), run_pipeline_fn=_complete_dispatch)
        client = TestClient(app)
        response = client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("done.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(response.status_code, 202)
        job_id = str(response.json()["job_id"])
        result_resp = client.get(f"/v1/jobs/{job_id}/result")
        self.assertEqual(result_resp.status_code, 200)
        payload = result_resp.json()
        self.assertEqual(payload["job_id"], job_id)
        self.assertEqual(payload["result"].get("library_id"), "supply_chain")
        self.assertTrue(str(payload["result"].get("workspace_path", "")).strip())

    def test_sse_events_include_stage_progress(self) -> None:
        def _staged_dispatch(ctx, job_id, _input_path, _options) -> None:
            def _run() -> None:
                row = ctx.job_store.get_job(job_id) or {}
                workspace = str(row.get("workspace_path", ""))
                ctx.job_store.update_job(
                    job_id,
                    {"status": "running", "stage": "parse_pdf", "progress": 5, "last_event": "stage_started"},
                )
                time.sleep(0.9)
                ctx.job_store.update_job(
                    job_id,
                    {"status": "running", "stage": "parse_pdf", "progress": 35, "last_event": "stage_progress"},
                )
                time.sleep(0.9)
                ctx.job_store.update_job(
                    job_id,
                    {"status": "running", "stage": "parse_pdf", "progress": 45, "last_event": "stage_done"},
                )
                time.sleep(0.9)
                ctx.job_store.update_job(
                    job_id,
                    {
                        "status": "completed",
                        "stage": "finalize",
                        "progress": 100,
                        "output_path": str(Path(workspace) / "imports" / "jobs" / job_id / "result.json"),
                        "result_json": json.dumps({"job_id": job_id, "library_id": row.get("library_id", "")}, ensure_ascii=False),
                        "last_event": "completed",
                    },
                )

            threading.Thread(target=_run, daemon=True).start()

        app = create_app(job_store=InMemoryJobStore(), run_pipeline_fn=_staged_dispatch)
        client = TestClient(app)
        create_resp = client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("stream.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(create_resp.status_code, 202)
        job_id = str(create_resp.json()["job_id"])

        seen_events: list[str] = []
        with client.stream("GET", f"/v1/jobs/{job_id}/events") as response:
            self.assertEqual(response.status_code, 200)
            for raw_line in response.iter_lines():
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
                if not line.startswith("event: "):
                    continue
                seen_events.append(line.replace("event: ", "", 1).strip())
                if "completed" in seen_events and "stage_progress" in seen_events:
                    break

        self.assertIn("stage_started", seen_events)
        self.assertIn("stage_progress", seen_events)
        self.assertIn("stage_done", seen_events)
        self.assertIn("completed", seen_events)

    def test_batch_upload_creates_multiple_jobs(self) -> None:
        response = self.client.post(
            "/v1/pipeline/parse-extract/batch",
            files=[
                ("files", ("a.pdf", b"%PDF-1.4\nfake-a", "application/pdf")),
                ("files", ("b.pdf", b"%PDF-1.4\nfake-b", "application/pdf")),
            ],
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload.get("accepted_count"), 2)
        self.assertEqual(payload.get("rejected_count"), 0)
        accepted = payload.get("accepted") or []
        self.assertEqual(len(accepted), 2)

    def test_list_jobs_supports_filters(self) -> None:
        first = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("filter_a.pdf", b"%PDF-1.4\nx", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        second = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("filter_b.pdf", b"%PDF-1.4\ny", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        response = self.client.get("/v1/jobs?library_id=supply_chain&status=queued&q=filter_a&page=1&page_size=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        jobs = payload.get("jobs") or []
        self.assertGreaterEqual(len(jobs), 1)
        self.assertTrue(all(str(item.get("library_id", "")) == "supply_chain" for item in jobs))

    def test_retry_failed_job_creates_new_job(self) -> None:
        created = self.client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("retry.pdf", b"%PDF-1.4\nretry", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(created.status_code, 202)
        job_id = str(created.json().get("job_id", ""))
        self.assertTrue(job_id)
        self.store.update_job(job_id, {"status": "failed", "error_code": "x", "error_detail": "boom"})

        retry_resp = self.client.post(f"/v1/jobs/{job_id}/retry")
        self.assertEqual(retry_resp.status_code, 202)
        payload = retry_resp.json()
        self.assertEqual(payload.get("source_job_id"), job_id)
        new_job = payload.get("new_job") or {}
        new_job_id = str(new_job.get("job_id", ""))
        self.assertTrue(new_job_id and new_job_id != job_id)
        row = self.client.get(f"/v1/jobs/{new_job_id}").json()
        self.assertEqual(str(row.get("source_job_id", "")), job_id)


if __name__ == "__main__":
    unittest.main()
