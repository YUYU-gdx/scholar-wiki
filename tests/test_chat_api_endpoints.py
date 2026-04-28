from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "serve_graph_api.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_serve_graph_api_chat_tests", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

make_handler = _MOD.make_handler
ThreadingHTTPServer = _MOD.ThreadingHTTPServer


_CHAT_SERVICE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "chat_service.py"
_CHAT_SPEC = importlib.util.spec_from_file_location("smj_pipeline_chat_service_for_fast_mode_tests", _CHAT_SERVICE_PATH)
if _CHAT_SPEC is None or _CHAT_SPEC.loader is None:
    raise RuntimeError(f"Unable to load chat service module: {_CHAT_SERVICE_PATH}")
_CHAT_MOD = importlib.util.module_from_spec(_CHAT_SPEC)
sys.modules[_CHAT_SPEC.name] = _CHAT_MOD
_CHAT_SPEC.loader.exec_module(_CHAT_MOD)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _FakeChatService:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, object]] = {}
        self.messages: dict[str, list[dict[str, object]]] = {}
        self.deleted: set[str] = set()
        self.last_submit_payload: dict[str, object] | None = None

    def create_session(self, title: str = "", default_mode: str = "fast", library_id: str = "") -> dict[str, object]:
        sid = f"sess_{len(self.sessions) + 1}"
        row = {"session_id": sid, "title": title or "新会话", "default_mode": default_mode, "library_id": str(library_id or "").strip()}
        self.sessions[sid] = row
        self.messages.setdefault(sid, [])
        return row

    def list_sessions(self, library_id: str = "") -> list[dict[str, object]]:
        lib = str(library_id or "").strip()
        return [v for k, v in self.sessions.items() if k not in self.deleted and str(v.get("library_id", "")) == lib]

    def get_session_with_messages(self, session_id: str, library_id: str = "") -> dict[str, object] | None:
        if session_id not in self.sessions or session_id in self.deleted:
            return None
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            return None
        return {"session": self.sessions[session_id], "messages": self.messages.get(session_id, [])}

    def delete_session(self, session_id: str, undo_window_seconds: int = 5, library_id: str = "") -> dict[str, object]:
        if session_id not in self.sessions or session_id in self.deleted:
            raise KeyError("session_not_found")
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            raise KeyError("session_not_found")
        self.deleted.add(session_id)
        return {
            "session_id": session_id,
            "deleted_at": "2026-01-01T00:00:00+00:00",
            "undo_window_seconds": int(undo_window_seconds),
            "undo_deadline": "2026-01-01T00:00:05+00:00",
        }

    def restore_session(self, session_id: str, library_id: str = "") -> dict[str, object]:
        if session_id not in self.sessions:
            return {"session_id": session_id, "restored": False, "error": "session_not_found"}
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            return {"session_id": session_id, "restored": False, "error": "session_not_found"}
        if session_id not in self.deleted:
            return {"session_id": session_id, "restored": False, "error": "restore_window_expired"}
        self.deleted.remove(session_id)
        return {"session_id": session_id, "restored": True}

    def submit_message(
        self,
        session_id: str,
        content: str,
        mode: str,
        provider: str,
        model: str,
        stream: bool,
        library_id: str = "",
    ) -> dict[str, str]:
        self.last_submit_payload = {
            "session_id": session_id,
            "content": content,
            "mode": mode,
            "provider": provider,
            "model": model,
            "stream": stream,
            "library_id": library_id,
        }
        if session_id not in self.sessions:
            raise KeyError("session_not_found")
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            raise KeyError("session_not_found")
        if "force_submit_error" in content:
            raise RuntimeError("codex_workspace_path_missing:library_id=lib_x")

        user_id = f"msg_user_{len(self.messages[session_id]) + 1}"
        assistant_id = "msg_assistant_failed" if "force_failed" in content else "msg_assistant_ok"

        self.messages[session_id].append({
            "message_id": user_id,
            "role": "user",
            "content": content,
            "status": "completed",
        })
        self.messages[session_id].append({
            "message_id": assistant_id,
            "role": "assistant",
            "content": "",
            "status": "running",
        })
        return {"user_message_id": user_id, "assistant_message_id": assistant_id}

    def read_events(self, message_id: str, cursor: int, wait_seconds: float = 20.0):
        _ = wait_seconds
        if message_id == "msg_assistant_failed":
            if cursor > 0:
                return [], cursor, True
            return (
                [
                    {"type": "started", "payload": {"phase": "start"}},
                    {"type": "failed", "payload": {"error": "synthetic_failure"}},
                ],
                2,
                True,
            )

        if message_id != "msg_assistant_ok":
            return [], cursor, True

        if cursor >= 3:
            return [], cursor, True

        rows = [
            {"type": "started", "payload": {"phase": "start"}},
            {"type": "delta", "payload": {"text": "hello"}},
            {
                "type": "completed",
                "payload": {
                    "answer": "hello world",
                    "citations": [{"id": "c1"}],
                },
            },
        ]
        return rows[cursor:], 3, True


class ChatApiEndpointsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
        views = {
            "meta": {},
            "nodes": {},
            "edges": [],
            "edge_index_by_node": {},
            "overview": {"node_ids": [], "edge_indexes": []},
            "paper_map": {},
        }
        chat_frontend = Path(__file__).resolve().parent.parent / "frontend" / "chat_embed"
        self.fake_chat_service = _FakeChatService()
        handler = make_handler(views, tmp_path, chat_frontend_dir=chat_frontend, literature_service=None, chat_service=self.fake_chat_service)
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.tmp.cleanup()

    def _request_json(self, method: str, path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return int(resp.status), json.loads(raw)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return int(exc.code), json.loads(raw or "{}")

    def _post_json(self, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        return self._request_json("POST", path, payload)

    def _get_json(self, path: str) -> tuple[int, dict[str, object]]:
        return self._request_json("GET", path)

    def _delete_json(self, path: str) -> tuple[int, dict[str, object]]:
        return self._request_json("DELETE", path)

    def _get_text(self, path: str) -> tuple[int, str]:
        req = Request(f"http://127.0.0.1:{self.port}{path}", method="GET")
        with urlopen(req) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="ignore")

    def _parse_sse_events(self, content: str) -> list[tuple[str, dict[str, object]]]:
        out: list[tuple[str, dict[str, object]]] = []
        event_name = ""
        data_line = ""
        for line in content.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data_line = line[len("data: ") :].strip()
            elif not line.strip() and event_name:
                payload = json.loads(data_line or "{}")
                out.append((event_name, payload))
                event_name = ""
                data_line = ""
        return out

    def test_create_list_detail_submit_and_stream_sequence(self) -> None:
        status, created = self._post_json("/chat/sessions", {"title": "abc", "default_mode": "fast", "library_id": "lib_a"})
        self.assertEqual(status, 201)
        self.assertTrue(str(created["session_id"]).startswith("sess_"))
        session_id = str(created["session_id"])

        status, listed = self._get_json("/chat/sessions?library_id=lib_a")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["sessions"]), 1)

        status, detail = self._get_json(f"/chat/sessions/{session_id}?library_id=lib_a")
        self.assertEqual(status, 200)
        self.assertEqual(detail["session"]["session_id"], session_id)

        status, submitted = self._post_json(
            f"/chat/sessions/{session_id}/messages",
            {
                "content": "hi",
                "mode": "fast",
                "provider": "glm",
                "model": "glm-4.5-flash",
                "stream": True,
                "library_id": "lib_a",
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(submitted["assistant_message_id"], "msg_assistant_ok")
        self.assertIn("stream?message_id=msg_assistant_ok", submitted["stream_url"])

        with urlopen(f"http://127.0.0.1:{self.port}{submitted['stream_url']}") as resp:
            text = resp.read().decode("utf-8", errors="ignore")

        events = self._parse_sse_events(text)
        event_names = [name for name, _ in events]
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(event_names[0], "started")
        self.assertIn("delta", event_names)
        self.assertEqual(event_names[-1], "completed")

        cursors = [int(payload.get("cursor", -1)) for _, payload in events]
        self.assertTrue(all(c > 0 for c in cursors))
        self.assertTrue(cursors[-1] >= cursors[0])

        status, text_cursor = self._get_text(f"/chat/sessions/{session_id}/stream?message_id=msg_assistant_ok&cursor=1")
        self.assertEqual(status, 200)
        self.assertIn("event: delta", text_cursor)

    def test_delete_and_restore_session(self) -> None:
        status, created = self._post_json("/chat/sessions", {"title": "delete-me", "default_mode": "fast", "library_id": "lib_a"})
        self.assertEqual(status, 201)
        session_id = str(created["session_id"])

        status, payload = self._delete_json(f"/chat/sessions/{session_id}?library_id=lib_a")
        self.assertEqual(status, 200)
        self.assertEqual(str(payload.get("session_id", "")), session_id)
        self.assertIn("undo_deadline", payload)

        status, listed = self._get_json("/chat/sessions?library_id=lib_a")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed.get("sessions", [])), 0)

        status, restored = self._post_json(f"/chat/sessions/{session_id}/restore?library_id=lib_a", {})
        self.assertEqual(status, 200)
        self.assertTrue(bool(restored.get("restored")))

        status, listed = self._get_json("/chat/sessions?library_id=lib_a")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed.get("sessions", [])), 1)

    def test_stream_can_emit_failed_terminal_event(self) -> None:
        _, created = self._post_json("/chat/sessions", {"title": "x", "default_mode": "fast", "library_id": "lib_a"})
        session_id = str(created["session_id"])
        _, submitted = self._post_json(
            f"/chat/sessions/{session_id}/messages",
            {
                "content": "force_failed",
                "mode": "fast",
                "provider": "glm",
                "model": "glm-4.5-flash",
                "stream": True,
                "library_id": "lib_a",
            },
        )

        with urlopen(f"http://127.0.0.1:{self.port}{submitted['stream_url']}") as resp:
            text = resp.read().decode("utf-8", errors="ignore")

        events = self._parse_sse_events(text)
        names = [x[0] for x in events]
        self.assertEqual(names[0], "started")
        self.assertEqual(names[-1], "failed")

    def test_parameter_validation_and_not_found_paths(self) -> None:
        status, created = self._post_json("/chat/sessions", {"title": "x", "default_mode": "fast", "library_id": "lib_a"})
        self.assertEqual(status, 201)
        session_id = str(created["session_id"])

        status, payload = self._post_json(
            f"/chat/sessions/{session_id}/messages",
            {"content": " ", "mode": "fast", "provider": "glm", "model": "glm-4.5-flash", "stream": True, "library_id": "lib_a"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "content_required")

        status, payload = self._post_json(
            f"/chat/sessions/{session_id}/messages",
            {"content": "hi", "mode": "fast", "provider": "glm", "model": "glm-4.5-flash", "stream": True},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "library_id_required")

        status, payload = self._post_json(
            "/chat/sessions/not_found/messages",
            {"content": "hi", "mode": "fast", "provider": "glm", "model": "glm-4.5-flash", "stream": True, "library_id": "lib_a"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("error"), "session_not_found")

        status, payload = self._get_json("/chat/sessions/not_found?library_id=lib_a")
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("error"), "session_not_found")

        status, payload = self._get_json(f"/chat/sessions/{session_id}/stream")
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "message_id_required")

    def test_submit_message_accepts_library_id(self) -> None:
        status, created = self._post_json("/chat/sessions", {"title": "abc", "default_mode": "fast", "library_id": "lib_a"})
        self.assertEqual(status, 201)
        session_id = str(created["session_id"])
        status, submitted = self._post_json(
            f"/chat/sessions/{session_id}/messages",
            {
                "content": "library test",
                "mode": "fast",
                "provider": "glm",
                "model": "glm-4.5-flash",
                "stream": True,
                "library_id": "lib_a",
            },
        )
        self.assertEqual(status, 202)
        self.assertTrue(str(submitted.get("assistant_message_id", "")).startswith("msg_assistant_"))
        self.assertIsNotNone(self.fake_chat_service.last_submit_payload)
        assert self.fake_chat_service.last_submit_payload is not None
        self.assertEqual(self.fake_chat_service.last_submit_payload.get("library_id"), "lib_a")

    def test_submit_message_structured_error_payload_on_unexpected_failure(self) -> None:
        status, created = self._post_json("/chat/sessions", {"title": "abc", "default_mode": "fast", "library_id": "lib_x"})
        self.assertEqual(status, 201)
        session_id = str(created["session_id"])
        status, payload = self._post_json(
            f"/chat/sessions/{session_id}/messages",
            {
                "content": "force_submit_error",
                "mode": "agent",
                "provider": "codex",
                "model": "codex-local",
                "stream": True,
                "library_id": "lib_x",
            },
        )
        self.assertEqual(status, 500)
        self.assertEqual(payload.get("error"), "chat_submit_failed")
        self.assertEqual(payload.get("error_code"), "codex_workspace_path_missing")
        self.assertEqual(payload.get("backend"), "codex")

    def test_provider_test_endpoint_validation(self) -> None:
        status, payload = self._post_json("/chat/provider-test", {})
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "provider_required")

        status, payload = self._post_json(
            "/chat/provider-test",
            {
                "provider_item": {
                    "id": "demo",
                    "type": "openai_compatible",
                    "api_key_env": "MISSING_PROVIDER_TEST_KEY",
                    "default_model": "demo-chat",
                    "base_url": "https://api.example.com/v1/chat/completions",
                }
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("error"), "provider_test_failed")
        self.assertIn("missing_env", str(payload.get("detail", "")))

    def test_frontend_chat_page_served_under_frontend_namespace(self) -> None:
        with urlopen(f"http://127.0.0.1:{self.port}/frontend/chat/") as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        self.assertIn("KN Graph AI 问答", html)
        self.assertIn("data-testid=\"new-session-btn\"", html)
        self.assertIn("data-testid=\"message-input\"", html)
        self.assertNotIn("流式输出已开启", html)


class ChatApiLoaderIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
        views = {
            "meta": {},
            "nodes": {},
            "edges": [],
            "edge_index_by_node": {},
            "overview": {"node_ids": [], "edge_indexes": []},
            "paper_map": {},
        }
        chat_frontend = Path(__file__).resolve().parent.parent / "frontend" / "chat_embed"
        handler = make_handler(views, tmp_path, chat_frontend_dir=chat_frontend, literature_service=None, chat_service=None)
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.tmp.cleanup()

    def test_default_loader_can_create_session(self) -> None:
        body = json.dumps({"title": "abc", "default_mode": "fast", "library_id": "lib_a"}, ensure_ascii=False).encode("utf-8")
        req = Request(
            f"http://127.0.0.1:{self.port}/chat/sessions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(resp.status, 201)
        self.assertIn("session_id", payload)


class _StubModelRouter:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90) -> str:
        _ = provider, model, messages, timeout_seconds
        self.calls += 1
        if self.calls == 1:
            return ""
        return "synthetic_answer"

    def stream(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90):
        _ = provider, model, messages, timeout_seconds
        yield "synthetic_answer"


class _FailingModelRouter:
    def complete(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90) -> str:
        _ = provider, model, messages, timeout_seconds
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    def stream(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90):
        _ = provider, model, messages, timeout_seconds
        raise RuntimeError("HTTP Error 429: Too Many Requests")
        yield ""


class ChatServiceFastModeFallbackCitationTest(unittest.TestCase):
    def test_fast_mode_fails_when_no_paragraph_context(self) -> None:
        service = _CHAT_MOD.ChatService(
            literature_search_fn=lambda query, top_k: {"keyword_hits": [], "rag_hits": []},
            graph_search_fn=lambda query, top_k: [],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
        )
        service._models = _StubModelRouter()

        with self.assertRaises(RuntimeError) as ctx:
            service._run_fast(
                message_id="msg_test_fast_no_hit",
                query="no results query",
                provider="glm",
                model="glm-4.5-flash",
                stream=False,
                library_id="lib_a",
            )
        self.assertIn("paragraph_context_unavailable", str(ctx.exception))


class ChatServiceModelDegradedFallbackTest(unittest.TestCase):
    def test_fast_mode_returns_completed_result_when_model_rate_limited(self) -> None:
        service = _CHAT_MOD.ChatService(
            literature_search_fn=lambda query, top_k: {
                "keyword_hits": [
                    {
                        "id": "s1",
                        "level": "sentence",
                        "text": "sentence-hit",
                        "context": {"paragraph": {"text": "paragraph-hit"}},
                    }
                ],
                "rag_hits": [],
            },
            graph_search_fn=lambda query, top_k: [],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
        )
        service._models = _FailingModelRouter()

        result = service._run_fast(
            message_id="msg_test_fast_model_429",
            query="rate limit query",
            provider="glm",
            model="glm-4.5-flash",
            stream=False,
            library_id="lib_a",
        )

        self.assertIn("model_degraded", result["retrieval_trace"])
        self.assertIn("429", str(result["retrieval_trace"]["model_degraded"]))
        self.assertGreaterEqual(len(result["citations"]), 1)
        self.assertIn("降级原因", result["answer"])


if __name__ == "__main__":
    unittest.main()

