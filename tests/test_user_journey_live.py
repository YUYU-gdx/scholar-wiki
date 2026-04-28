from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_API_PATH = REPO_ROOT / "scripts" / "smj_pipeline" / "serve_graph_api.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_json(base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8") or "{}")


def _wait_http_ok(url: str, timeout_s: float = 40.0) -> bool:
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


class JourneyLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if str(os.getenv("KN_GRAPH_ENABLE_LIVE_LLM", "")).strip() != "1":
            raise unittest.SkipTest("live_llm_disabled: set KN_GRAPH_ENABLE_LIVE_LLM=1 to run")
        if not str(os.getenv("ZHIPU_API_KEY", "")).strip():
            raise unittest.SkipTest("missing_env: ZHIPU_API_KEY")

        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.root = root
        views_json = root / "graph_views.json"
        views_json.write_text(
            json.dumps(
                {
                    "meta": {"paper_count": 1},
                    "nodes": {"var::a": {"id": "var::a", "type": "variable", "label": "A", "name": "A"}},
                    "edges": [],
                    "moderation_links": [],
                    "interaction_links": [],
                    "edge_index_by_node": {"var::a": []},
                    "overview": {"node_ids": ["var::a"], "edge_indexes": []},
                    "paper_map": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

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
        cls._env["LITERATURE_LIBRARY_INDEX_ROOT"] = str(index_root)
        cls._env["LITERATURE_LIBRARY_WORKSPACES_ROOT"] = str(workspace_root)
        cls._env["LITERATURE_LIBRARY_REGISTRY_PATH"] = str(registry_path)
        cls._env["LITERATURE_DEFAULT_LIBRARY_ID"] = "supply_chain"

        cls.port = _free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                str(GRAPH_API_PATH),
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
        if not _wait_http_ok(f"{cls.base_url}/graph/overview", timeout_s=45.0):
            out, err = cls.proc.communicate(timeout=8)
            raise RuntimeError(f"live_server_start_failed\nstdout={out}\nstderr={err}")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "proc") and cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=8)
            except Exception:
                cls.proc.kill()
        if hasattr(cls, "_tmp"):
            cls._tmp.cleanup()

    def test_live_zhipu_provider_test(self) -> None:
        model = str(os.getenv("KN_GRAPH_LIVE_ZHIPU_MODEL", "")).strip() or "glm-4.5-flash"
        status, payload = _request_json(
            self.base_url,
            "POST",
            "/chat/provider-test",
            {
                "provider": "zhipu",
                "model": model,
                "prompt": "请只回复 OK",
                "options": {"timeout_seconds": 20},
            },
        )
        self.assertEqual(status, 200, msg=str(payload))
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual(str(payload.get("provider", "")), "zhipu")
        self.assertTrue(bool(str(payload.get("response_preview", "")).strip()))

    def test_live_codex_agent_session_message(self) -> None:
        status, health = _request_json(self.base_url, "GET", "/chat/codex/health")
        if status != 200 or not bool(health.get("available")):
            self.skipTest(f"codex_unavailable: {health}")

        status, session = _request_json(self.base_url, "POST", "/chat/sessions", {"title": "live", "library_id": "supply_chain"})
        self.assertEqual(status, 201, msg=str(session))
        sid = str(session.get("session_id", ""))
        self.assertTrue(sid)

        status, submitted = _request_json(
            self.base_url,
            "POST",
            f"/chat/sessions/{sid}/messages",
            {"content": "你好", "stream": True, "library_id": "supply_chain"},
        )
        self.assertEqual(status, 202, msg=str(submitted))
        stream_url = str(submitted.get("stream_url", "")).strip()
        self.assertTrue(stream_url)

        req = Request(f"{self.base_url}{stream_url}", method="GET")
        events: list[str] = []
        with urlopen(req, timeout=60) as resp:
            for line in resp.read().decode("utf-8", errors="ignore").splitlines():
                if line.startswith("event: "):
                    events.append(line[len("event: ") :].strip())
        self.assertIn("started", events)
        self.assertTrue(("completed" in events) or ("failed" in events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
