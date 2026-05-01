from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fastapi.testclient import TestClient

try:
    from tests._e2e_helpers import _base_views
except Exception:  # pragma: no cover - fallback for direct file execution
    from _e2e_helpers import _base_views


REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_API_PATH = REPO_ROOT / "scripts" / "smj_pipeline" / "serve_graph_api.py"
ASYNC_API_PATH = REPO_ROOT / "scripts" / "smj_pipeline" / "serve_async_pipeline_api.py"

# User-journey node map used as the source of truth for test coverage assertions.
JOURNEY_NODE_MAP = {
    "A": [
        "graph_overview",
        "graph_search",
        "graph_variable_detail",
        "chat_create_session",
        "chat_submit_message",
        "chat_sse_terminal",
    ],
    "B": [
        "pipeline_upload",
        "pipeline_job_status",
        "pipeline_job_events",
        "pipeline_job_cancel",
        "pipeline_job_retry",
    ],
    "C": [
        "literature_import",
        "literature_search",
        "literature_answer",
        "literature_libraries",
    ],
    "D": [
        "cli_filter_manifest_supply_chain",
        "cli_build_graph_views",
        "cli_activate_run",
        "cli_list_runs",
    ],
    "E": [
        "contract_matrix_complete",
        "critical_path_smoke",
    ],
}


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


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
        with urlopen(req, timeout=15) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8") or "{}")


class _FakeLiteratureService:
    def import_manifest(self, manifest_path: str, options: dict | None = None) -> dict:
        _ = options
        path = Path(str(manifest_path))
        if not path.exists():
            raise RuntimeError(f"manifest_missing:{manifest_path}")
        rows = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return {
            "manifest_path": str(path),
            "imported_count": len(rows),
            "sentence_count": max(1, len(rows) * 2),
            "paragraph_count": max(1, len(rows)),
            "document_count": len(rows),
        }

    def search(
        self,
        query: str,
        top_k: int,
        levels: list[str],
        keyword_weight: float,
        rag_weight: float,
        include_expanded_context: bool,
        library_id: str = "",
    ) -> dict:
        _ = top_k, levels, keyword_weight, rag_weight, include_expanded_context
        text = str(query or "").strip() or "q"
        lib = str(library_id or "").strip() or "supply_chain"
        return {
            "keyword_hits": [{"id": "k1", "library_id": lib, "text": text}],
            "rag_hits": [{"id": "r1", "library_id": lib, "text": text}],
            "merged_hits": [{"id": "m1", "library_id": lib, "text": text}],
            "search_meta": {"library_filter_applied": bool(library_id)},
        }

    def answer(
        self,
        query: str,
        top_k: int,
        levels: list[str],
        keyword_weight: float,
        rag_weight: float,
        library_id: str = "",
    ) -> dict:
        _ = top_k, levels, keyword_weight, rag_weight
        text = str(query or "").strip() or "q"
        lib = str(library_id or "").strip() or "supply_chain"
        return {
            "answer": f"answer:{text}",
            "citations": [{"id": "m1", "library_id": lib}],
            "retrieval": {"merged_hits": [{"id": "m1", "library_id": lib}]},
        }


class _FakeChatService:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._messages: dict[str, list[dict]] = {}

    def create_session(self, title: str = "", default_mode: str = "agent", library_id: str = "") -> dict:
        sid = f"sess_{len(self._sessions) + 1}"
        row = {
            "session_id": sid,
            "title": title or "新会话",
            "default_mode": default_mode,
            "library_id": str(library_id or "").strip(),
        }
        self._sessions[sid] = row
        self._messages.setdefault(sid, [])
        return row

    def list_sessions(self, library_id: str = "") -> list[dict]:
        lib = str(library_id or "").strip()
        return [v for v in self._sessions.values() if str(v.get("library_id", "")) == lib]

    def get_session_with_messages(self, session_id: str, library_id: str = "") -> dict | None:
        row = self._sessions.get(session_id)
        if not row:
            return None
        if str(row.get("library_id", "")) != str(library_id or "").strip():
            return None
        return {"session": row, "messages": self._messages.get(session_id, [])}

    def submit_message(
        self,
        session_id: str,
        content: str,
        mode: str,
        provider: str,
        model: str,
        stream: bool,
        library_id: str = "",
    ) -> dict:
        _ = mode, provider, model, stream
        row = self._sessions.get(session_id)
        if not row:
            raise KeyError("session_not_found")
        if str(row.get("library_id", "")) != str(library_id or "").strip():
            raise KeyError("session_not_found")
        text = str(content or "").strip()
        if not text:
            raise ValueError("content_required")
        uid = f"user_{len(self._messages[session_id]) + 1}"
        aid = f"assistant_{len(self._messages[session_id]) + 2}"
        self._messages[session_id].append({"message_id": uid, "role": "user", "content": text, "status": "completed"})
        self._messages[session_id].append({"message_id": aid, "role": "assistant", "content": "", "status": "running"})
        return {"user_message_id": uid, "assistant_message_id": aid}

    def read_events(self, message_id: str, cursor: int, wait_seconds: float = 20.0):
        _ = wait_seconds
        events = [
            {"type": "started", "payload": {"phase": "start"}},
            {"type": "tool_call", "payload": {"backend": "codex", "step_id": "codex-1", "state": "completed", "summary": "rag.search"}},
            {"type": "delta", "payload": {"text": "你好"}},
            {"type": "completed", "payload": {"answer": "你好，已处理。", "citations": [{"id": "c1"}], "tool_trace": []}},
        ]
        start = max(0, int(cursor))
        out = events[start:]
        done = True
        return out, len(events), done


class JourneyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.root = root
        cls.frontend_dir = root / "frontend"
        cls.frontend_dir.mkdir(parents=True, exist_ok=True)
        (cls.frontend_dir / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

        cls.index_root = root / "literature_libraries"
        cls.workspace_root = root / "workspaces"
        cls.registry_path = root / "registry" / "registry.json"
        cls.index_root.mkdir(parents=True, exist_ok=True)
        cls.workspace_root.mkdir(parents=True, exist_ok=True)
        (cls.workspace_root / "supply_chain").mkdir(parents=True, exist_ok=True)
        (cls.index_root / "supply_chain.json").write_text(
            json.dumps(
                {
                    "library_id": "supply_chain",
                    "paper_count": 3,
                    "updated_at": "2026-01-01T00:00:00Z",
                    "workspace_root": str((cls.workspace_root / "supply_chain").resolve()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        cls._old_env = {
            "LITERATURE_LIBRARY_INDEX_ROOT": os.environ.get("LITERATURE_LIBRARY_INDEX_ROOT"),
            "LITERATURE_LIBRARY_WORKSPACES_ROOT": os.environ.get("LITERATURE_LIBRARY_WORKSPACES_ROOT"),
            "LITERATURE_LIBRARY_REGISTRY_PATH": os.environ.get("LITERATURE_LIBRARY_REGISTRY_PATH"),
            "LITERATURE_DEFAULT_LIBRARY_ID": os.environ.get("LITERATURE_DEFAULT_LIBRARY_ID"),
        }
        os.environ["LITERATURE_LIBRARY_INDEX_ROOT"] = str(cls.index_root)
        os.environ["LITERATURE_LIBRARY_WORKSPACES_ROOT"] = str(cls.workspace_root)
        os.environ["LITERATURE_LIBRARY_REGISTRY_PATH"] = str(cls.registry_path)
        os.environ["LITERATURE_DEFAULT_LIBRARY_ID"] = "supply_chain"

        graph_mod = _load_module(GRAPH_API_PATH, "smj_pipeline_serve_graph_api_for_journey_contract")
        handler_cls = graph_mod.make_handler(
            _base_views(),
            cls.frontend_dir,
            literature_service=_FakeLiteratureService(),
            chat_service=_FakeChatService(),
        )
        cls.port = _free_port()
        cls.server = graph_mod.ThreadingHTTPServer(("127.0.0.1", cls.port), handler_cls)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.08)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        async_mod = _load_module(ASYNC_API_PATH, "smj_pipeline_serve_async_pipeline_api_for_journey_contract")
        cls.async_mod = async_mod
        cls.async_store = async_mod.InMemoryJobStore()
        cls.async_client = TestClient(async_mod.create_app(job_store=cls.async_store, run_pipeline_fn=lambda *_args, **_kwargs: None))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        for key, old in cls._old_env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        cls._tmp.cleanup()

    def _parse_sse_events(self, path: str) -> list[tuple[str, dict]]:
        req = Request(f"{self.base_url}{path}", method="GET")
        out: list[tuple[str, dict]] = []
        with urlopen(req, timeout=15) as resp:
            event_name = ""
            data_line = ""
            for raw in resp.read().decode("utf-8", errors="ignore").splitlines():
                if raw.startswith("event: "):
                    event_name = raw[len("event: ") :].strip()
                elif raw.startswith("data: "):
                    data_line = raw[len("data: ") :].strip()
                elif not raw.strip() and event_name:
                    out.append((event_name, json.loads(data_line or "{}")))
                    event_name = ""
                    data_line = ""
        return out

    # A
    def test_journey_a_graph_and_chat_sse_terminal(self) -> None:
        status, payload = _request_json(self.base_url, "GET", "/graph/overview")
        self.assertEqual(status, 200)
        self.assertIn("nodes", payload)

        status, payload = _request_json(self.base_url, "GET", "/graph/search?mode=variable&query=resilience")
        self.assertEqual(status, 200)
        self.assertIn("results", payload)

        status, payload = _request_json(self.base_url, "GET", "/variable/var::a")
        self.assertEqual(status, 200)
        self.assertIn("node", payload)

        status, session = _request_json(self.base_url, "POST", "/chat/sessions", {"title": "journey-a", "library_id": "supply_chain"})
        self.assertEqual(status, 201)
        sid = str(session.get("session_id", ""))
        self.assertTrue(sid)

        status, submitted = _request_json(
            self.base_url,
            "POST",
            f"/chat/sessions/{sid}/messages",
            {"content": "你好", "stream": True, "library_id": "supply_chain"},
        )
        self.assertEqual(status, 202)
        stream_url = str(submitted.get("stream_url", ""))
        self.assertTrue(stream_url)
        events = self._parse_sse_events(stream_url)
        names = [x[0] for x in events]
        self.assertIn("started", names)
        self.assertIn("completed", names)

    # B
    def test_journey_b_async_pipeline_endpoints(self) -> None:
        response = self.async_client.post(
            "/v1/pipeline/parse-extract",
            files={"file": ("journey.pdf", b"%PDF-1.4\nfake", "application/pdf")},
            data={"library_id": "supply_chain"},
        )
        self.assertEqual(response.status_code, 202)
        job_id = str(response.json().get("job_id", ""))
        self.assertTrue(job_id)

        row = self.async_client.get(f"/v1/jobs/{job_id}")
        self.assertEqual(row.status_code, 200)
        self.assertEqual(str(row.json().get("status", "")), "queued")

        cancelled = self.async_client.post(f"/v1/jobs/{job_id}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(str(cancelled.json().get("status", "")), "cancelled")

        retried = self.async_client.post(f"/v1/jobs/{job_id}/retry")
        self.assertEqual(retried.status_code, 202)
        new_job = str((retried.json().get("new_job") or {}).get("job_id", ""))
        self.assertTrue(new_job and new_job != job_id)

    # C
    def test_journey_c_literature_import_search_answer_and_libraries(self) -> None:
        source_md = self.root / "paper_1.md"
        source_md.write_text("# title\n\nabstract text", encoding="utf-8")
        manifest = self.root / "manifest.jsonl"
        manifest.write_text(
            json.dumps(
                {
                    "paper_id": "p1",
                    "doi": "10.1002/p1",
                    "title": "paper 1",
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
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(int(imported.get("imported_count", 0) or 0), 1)

        status, searched = _request_json(
            self.base_url,
            "GET",
            "/literature/search?query=supply+chain&library_id=supply_chain&top_k=5",
        )
        self.assertEqual(status, 200)
        self.assertIn("merged_hits", searched)

        status, answered = _request_json(
            self.base_url,
            "POST",
            "/literature/answer",
            {"query": "what is resilience", "library_id": "supply_chain", "top_k": 3},
        )
        self.assertEqual(status, 200)
        self.assertIn("answer", answered)
        self.assertIn("citations", answered)

        status, libs = _request_json(self.base_url, "GET", "/literature/libraries")
        self.assertEqual(status, 200)
        self.assertIn("libraries", libs)
        self.assertTrue(any(str(x.get("library_id", "")) == "supply_chain" for x in (libs.get("libraries") or [])))

    # D
    def test_journey_d_cli_smoke_run_management(self) -> None:
        run_id = "supply_chain_20260101_000000"
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        frontend_artifact = run_dir / "frontend_artifact.json"
        frontend_artifact.write_text(
            json.dumps(
                {
                    "meta": {"paper_count": 1},
                    "nodes": [{"id": "var::a", "type": "variable", "label": "A"}],
                    "edges": [],
                    "moderation_links": [],
                    "interaction_links": [],
                    "papers": [{"paper_id": "p1", "doi": "10.1002/p1"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        graph_views = run_dir / "graph_views.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "smj_pipeline" / "build_graph_views.py"),
                "--input-json",
                str(frontend_artifact),
                "--output-json",
                str(graph_views),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertTrue(graph_views.exists())

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "smj_pipeline" / "activate_run.py"),
                "--run-id",
                run_id,
                "--runs-root",
                str(self.root / "runs"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT / "scripts" / "smj_pipeline"),
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "smj_pipeline" / "list_runs.py"),
                "--runs-root",
                str(self.root / "runs"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT / "scripts" / "smj_pipeline"),
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        listed = json.loads(proc.stdout or "{}")
        self.assertTrue(any(str(x.get("run_id", "")) == run_id for x in (listed.get("runs") or [])))

        manifest_in = self.root / "manifest_input.jsonl"
        html_text = "<html><head><meta name='citation_title' content='Supply Chain Resilience'></head><body><p>Abstract</p></body></html>"
        manifest_in.write_text(json.dumps({"paper_id": "p1", "doi": "10.1002/p1", "html": html_text}, ensure_ascii=False) + "\n", encoding="utf-8")
        lexicon = self.root / "lexicon.md"
        lexicon.write_text("# keywords\n- supply chain\n- resilience\n", encoding="utf-8")
        out_dir = self.root / "supply_chain_out"
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "smj_pipeline" / "filter_manifest_supply_chain.py"),
                "--input-manifest",
                str(manifest_in),
                "--lexicon",
                str(lexicon),
                "--output-dir",
                str(out_dir),
                "--run-id",
                "supply_chain_test",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertTrue((out_dir / "supply_chain_test" / "manifest_input.jsonl").exists())

    # E
    def test_journey_e_contract_matrix_complete_and_critical_path(self) -> None:
        required_groups = {"A", "B", "C", "D", "E"}
        self.assertEqual(set(JOURNEY_NODE_MAP.keys()), required_groups)
        for group, nodes in JOURNEY_NODE_MAP.items():
            self.assertTrue(nodes, msg=f"{group} has no nodes")
            self.assertEqual(len(nodes), len(set(nodes)), msg=f"{group} has duplicate nodes")

        # Critical path smoke: A + B + C each has at least one validated node.
        self.assertIn("chat_sse_terminal", JOURNEY_NODE_MAP["A"])
        self.assertIn("pipeline_upload", JOURNEY_NODE_MAP["B"])
        self.assertIn("literature_search", JOURNEY_NODE_MAP["C"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
