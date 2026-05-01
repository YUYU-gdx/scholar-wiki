from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_json(base_url: str, method: str, path: str, payload: dict | None = None, timeout: float = 25.0) -> tuple[int, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8") or "{}")


def _wait_http_ok(url: str, timeout_s: float = 50.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            with urlopen(url, timeout=3) as resp:
                if int(resp.status) == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.6)
    return False


class JourneyLiveFullTest(unittest.TestCase):
    """Live e2e against real KN Graph backend APIs.

    Enabled only when KN_GRAPH_ENABLE_LIVE_E2E=1.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if str(os.getenv("KN_GRAPH_ENABLE_LIVE_E2E", "")).strip() != "1":
            raise unittest.SkipTest("live_e2e_disabled: set KN_GRAPH_ENABLE_LIVE_E2E=1 to run")
        if not str(os.getenv("ZHIPU_API_KEY", "")).strip():
            raise RuntimeError("missing_env: ZHIPU_API_KEY")

        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.root = root

        # seed minimal graph data
        views_json = root / "graph_views.json"
        views_json.write_text(
            json.dumps(
                {
                    "meta": {"paper_count": 1},
                    "nodes": {
                        "var::a": {"id": "var::a", "type": "variable", "label": "Resilience", "name": "Resilience"},
                        "var::b": {"id": "var::b", "type": "variable", "label": "Performance", "name": "Performance"},
                    },
                    "edges": [
                        {
                            "id": "edge::1",
                            "source": "var::a",
                            "target": "var::b",
                            "paper_id": "p1",
                            "doi": "10.1002/test",
                            "relation_type": "direct",
                            "direction": "positive",
                        }
                    ],
                    "moderation_links": [],
                    "interaction_links": [],
                    "edge_index_by_node": {"var::a": [0], "var::b": [0]},
                    "overview": {"node_ids": ["var::a", "var::b"], "edge_indexes": [0]},
                    "paper_map": {
                        "p1": {
                            "paper_id": "p1",
                            "doi": "10.1002/test",
                            "main_effects": [{"source": "Resilience", "target": "Performance", "direction": "positive"}],
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # seed literature library registry roots
        index_root = root / "literature_libraries"
        workspace_root = root / "workspaces"
        registry_path = root / "registry" / "registry.json"
        index_root.mkdir(parents=True, exist_ok=True)
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "supply_chain").mkdir(parents=True, exist_ok=True)
        (index_root / "supply_chain.json").write_text(
            json.dumps(
                {
                    "library_id": "supply_chain",
                    "paper_count": 3,
                    "updated_at": "2026-01-01T00:00:00Z",
                    "workspace_root": str((workspace_root / "supply_chain").resolve()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        cls._env = os.environ.copy()
        cls._env["KN_GRAPH_DATA_DIR"] = str(root / "kn_data")
        cls._env["LITERATURE_LIBRARY_INDEX_ROOT"] = str(index_root)
        cls._env["LITERATURE_LIBRARY_WORKSPACES_ROOT"] = str(workspace_root)
        cls._env["LITERATURE_LIBRARY_REGISTRY_PATH"] = str(registry_path)
        cls._env["LITERATURE_DEFAULT_LIBRARY_ID"] = "supply_chain"
        cls._env["PIPELINE_EXECUTOR"] = "inline"

        cls.port = _free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kn_graph",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--views-json",
                str(views_json),
                "--allow-non-supply-chain",
            ],
            cwd=str(REPO_ROOT),
            env=cls._env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if not _wait_http_ok(f"{cls.base_url}/healthz", timeout_s=55.0):
            out, err = cls.proc.communicate(timeout=8)
            raise RuntimeError(f"live_server_start_failed\nstdout={out}\nstderr={err}")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "proc") and cls.proc:
            try:
                if cls.proc.poll() is None:
                    cls.proc.terminate()
                    try:
                        cls.proc.wait(timeout=10)
                    except Exception:
                        cls.proc.kill()
                        cls.proc.wait(timeout=10)
                else:
                    cls.proc.kill()
            except Exception:
                try:
                    cls.proc.kill()
                except Exception:
                    pass
            try:
                if cls.proc.stdout:
                    cls.proc.stdout.close()
                if cls.proc.stderr:
                    cls.proc.stderr.close()
            except Exception:
                pass
        if hasattr(cls, "_tmp"):
            root = getattr(cls._tmp, "name", "")
            cleaned = False
            for _ in range(8):
                try:
                    if root and Path(root).exists():
                        shutil.rmtree(root, ignore_errors=False)
                    cleaned = True
                    break
                except Exception:
                    time.sleep(0.5)
            if not cleaned:
                shutil.rmtree(root, ignore_errors=True)

    def test_01_health_and_graph_and_workspace(self) -> None:
        status, payload = _request_json(self.base_url, "GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("status"), "ok")

        status, overview = _request_json(self.base_url, "GET", "/graph/overview?library_id=supply_chain")
        self.assertEqual(status, 200)
        self.assertIn("nodes", overview)

        status, found = _request_json(self.base_url, "GET", "/graph/search?mode=variable&query=resilience&library_id=supply_chain")
        self.assertEqual(status, 200)
        self.assertIn("results", found)

        status, variable = _request_json(self.base_url, "GET", "/variable/var::a?library_id=supply_chain")
        self.assertEqual(status, 200)
        self.assertIn("node", variable)

        status, save_layout = _request_json(
            self.base_url,
            "POST",
            "/api/v2/workspace/layout",
            {"name": "journey_live", "layout": {"panels": [{"type": "graph"}, {"type": "chat"}]}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(str(save_layout.get("name", "")), "journey_live")

        status, get_layout = _request_json(self.base_url, "GET", "/api/v2/workspace/layout?name=journey_live")
        self.assertEqual(status, 200)
        self.assertEqual(str(get_layout.get("name", "")), "journey_live")

    def test_02_literature_and_pipeline_endpoints(self) -> None:
        status, libs = _request_json(self.base_url, "GET", "/literature/libraries")
        self.assertEqual(status, 200)
        self.assertIn("libraries", libs)

        source_md = self.root / "live_paper.md"
        source_md.write_text("# title\n\nsupply chain resilience improves performance", encoding="utf-8")
        manifest = self.root / "live_manifest.jsonl"
        manifest.write_text(
            json.dumps(
                {
                    "paper_id": "live_p1",
                    "doi": "10.1002/live-p1",
                    "title": "live paper 1",
                    "source_path": str(source_md),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        status, imported = _request_json(
            self.base_url,
            "POST",
            "/literature/import",
            {"manifest_path": str(manifest), "library_id": "supply_chain"},
            timeout=120.0,
        )
        self.assertEqual(status, 200, msg=str(imported))
        self.assertGreaterEqual(int(imported.get("imported_count", 0) or 0), 1)

        status, search = _request_json(
            self.base_url,
            "GET",
            "/literature/search?query=supply+chain&library_id=supply_chain&top_k=3",
            timeout=60.0,
        )
        self.assertEqual(status, 200, msg=str(search))
        self.assertIn("merged_hits", search)

        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
        body = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"library_id\"\r\n\r\n"
            "supply_chain\r\n"
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename=\"live.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = Request(
            f"{self.base_url}/v1/pipeline/parse-extract",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            self.assertEqual(int(resp.status), 202)
            created = json.loads(resp.read().decode("utf-8") or "{}")

        job_id = str(created.get("job_id", ""))
        self.assertTrue(job_id)

        status, job = _request_json(self.base_url, "GET", f"/v1/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertIn("status", job)

        status, cancel = _request_json(self.base_url, "POST", f"/v1/jobs/{job_id}/cancel")
        self.assertIn(status, (200, 400, 409))
        self.assertTrue(bool(cancel))

    def test_03_chat_session_crud_and_optional_real_provider_call(self) -> None:
        status, session = _request_json(
            self.base_url,
            "POST",
            "/chat/sessions",
            {"title": "live-journey", "library_id": "supply_chain"},
        )
        self.assertEqual(status, 201, msg=str(session))
        sid = str(session.get("session_id", ""))
        self.assertTrue(sid)

        status, listed = _request_json(self.base_url, "GET", "/chat/sessions?library_id=supply_chain")
        self.assertEqual(status, 200)
        self.assertIn("sessions", listed)

        status, detail = _request_json(self.base_url, "GET", f"/chat/sessions/{sid}?library_id=supply_chain")
        self.assertEqual(status, 200)
        self.assertIn("session", detail)

        # send_message currently defaults to codex backend; this must succeed when codex env is ready.
        status, submit = _request_json(
            self.base_url,
            "POST",
            f"/chat/sessions/{sid}/messages",
            {
                "content": "hello live",
                "stream": True,
                "library_id": "supply_chain",
                "provider": "zhipu",
                "model": str(os.getenv("KN_GRAPH_LIVE_ZHIPU_MODEL", "")).strip() or "glm-4.5-flash",
            },
            timeout=45.0,
        )
        self.assertEqual(status, 202, msg=str(submit))
        self.assertTrue(bool(submit))

        status, deleted = _request_json(self.base_url, "DELETE", f"/chat/sessions/{sid}?library_id=supply_chain")
        self.assertEqual(status, 200)
        self.assertEqual(str(deleted.get("session_id", "")), sid)
        self.assertTrue(bool(str(deleted.get("deleted_at", "")).strip()))

        status, restored = _request_json(self.base_url, "POST", f"/chat/sessions/{sid}/restore?library_id=supply_chain")
        self.assertIn(status, (200, 404, 409))
        self.assertTrue(bool(restored))

        model = str(os.getenv("KN_GRAPH_LIVE_ZHIPU_MODEL", "")).strip() or "glm-4.5-flash"
        status, provider = _request_json(
            self.base_url,
            "POST",
            "/chat/provider-test",
            {
                "provider": "zhipu",
                "model": model,
                "prompt": "Please reply with OK only.",
                "options": {"timeout_seconds": 25},
            },
            timeout=60.0,
        )
        self.assertEqual(status, 200, msg=str(provider))
        self.assertTrue(bool(provider.get("ok")))
        self.assertTrue(bool(str(provider.get("response_preview", "")).strip()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
