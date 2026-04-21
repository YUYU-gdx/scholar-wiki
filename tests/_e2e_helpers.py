from __future__ import annotations

import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def load_graph_api_module() -> Any:
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "serve_graph_api.py"
    spec = importlib.util.spec_from_file_location("smj_pipeline_serve_graph_api_for_playwright_e2e", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeChatService:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}

    def create_session(self, title: str = "", default_mode: str = "fast") -> dict[str, Any]:
        sid = f"sess_{len(self.sessions) + 1}"
        row = {"session_id": sid, "title": title or "新会话", "default_mode": default_mode}
        self.sessions[sid] = row
        self.messages.setdefault(sid, [])
        return row

    def list_sessions(self) -> list[dict[str, Any]]:
        return list(self.sessions.values())

    def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        if session_id not in self.sessions:
            return None
        return {"session": self.sessions[session_id], "messages": self.messages.get(session_id, [])}

    def submit_message(
        self,
        session_id: str,
        content: str,
        mode: str,
        provider: str,
        model: str,
        stream: bool,
    ) -> dict[str, str]:
        _ = mode, provider, model, stream
        if session_id not in self.sessions:
            raise KeyError("session_not_found")
        if not str(content or "").strip():
            raise ValueError("content_required")

        user_id = f"msg_user_{len(self.messages[session_id]) + 1}"
        assistant_id = "msg_assistant_failed" if "force_failed" in content else "msg_assistant_ok"
        self.messages[session_id].append(
            {
                "message_id": user_id,
                "role": "user",
                "content": content,
                "status": "completed",
            }
        )
        self.messages[session_id].append(
            {
                "message_id": assistant_id,
                "role": "assistant",
                "content": "",
                "status": "running",
            }
        )
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


class GraphChatE2EHarness:
    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._server = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "GraphChatE2EHarness":
        mod = load_graph_api_module()
        make_handler = mod.make_handler
        thread_server = mod.ThreadingHTTPServer
        frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "graph_3d"

        views = {
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
                    "verification": "supported",
                    "strength": 1.0,
                    "evidence_anchor": "H1",
                }
            ],
            "edge_index_by_node": {"var::a": [0], "var::b": [0]},
            "overview": {"node_ids": ["var::a", "var::b"], "edge_indexes": [0]},
            "paper_map": {
                "p1": {
                    "paper_id": "p1",
                    "doi": "10.1002/test",
                    "main_effects": [{"source": "Resilience", "target": "Performance", "direction": "positive"}],
                }
            },
        }

        chat_frontend = Path(__file__).resolve().parent.parent / "frontend" / "chat_embed"
        handler = make_handler(
            views,
            frontend_dir,
            chat_frontend_dir=chat_frontend,
            literature_service=None,
            chat_service=FakeChatService(),
        )

        port = _free_port()
        self._server = thread_server(("127.0.0.1", port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.08)
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._tmp is not None:
            self._tmp.cleanup()


class WorkbenchE2EHarness:
    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._server = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "WorkbenchE2EHarness":
        mod = load_graph_api_module()
        make_handler = mod.make_handler
        thread_server = mod.ThreadingHTTPServer
        frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "graph_3d"
        workbench_frontend = Path(__file__).resolve().parent.parent / "frontend" / "workbench_spa"
        chat_frontend = Path(__file__).resolve().parent.parent / "frontend" / "chat_embed"

        views = {
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
                    "verification": "supported",
                    "strength": 1.0,
                    "evidence_anchor": "H1",
                }
            ],
            "edge_index_by_node": {"var::a": [0], "var::b": [0]},
            "overview": {"node_ids": ["var::a", "var::b"], "edge_indexes": [0]},
            "paper_map": {
                "p1": {
                    "paper_id": "p1",
                    "doi": "10.1002/test",
                    "main_effects": [{"source": "Resilience", "target": "Performance", "direction": "positive"}],
                }
            },
        }
        handler = make_handler(
            views,
            frontend_dir,
            workbench_frontend_dir=workbench_frontend,
            chat_frontend_dir=chat_frontend,
            literature_service=None,
            chat_service=FakeChatService(),
        )

        port = _free_port()
        self._server = thread_server(("127.0.0.1", port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.08)
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._tmp is not None:
            self._tmp.cleanup()


def ensure_playwright_ready() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return False, f"playwright_import_failed: {exc}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body>ok</body></html>")
            browser.close()
        return True, ""
    except Exception as exc:
        return False, f"playwright_browser_unavailable: {exc}"
