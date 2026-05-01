from __future__ import annotations

import importlib.util
import json
import os
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


def _pick_existing_dir(*candidates: Path) -> Path:
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


class FakeChatService:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}

    def create_session(self, title: str = "", default_mode: str = "fast", library_id: str = "") -> dict[str, Any]:
        sid = f"sess_{len(self.sessions) + 1}"
        row = {
            "session_id": sid,
            "title": title or "新会话",
            "default_mode": default_mode,
            "library_id": str(library_id or "").strip(),
        }
        self.sessions[sid] = row
        self.messages.setdefault(sid, [])
        return row

    def list_sessions(self, library_id: str = "") -> list[dict[str, Any]]:
        lib = str(library_id or "").strip()
        return [row for row in self.sessions.values() if str(row.get("library_id", "")) == lib]

    def get_session_with_messages(self, session_id: str, library_id: str = "") -> dict[str, Any] | None:
        if session_id not in self.sessions:
            return None
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            return None
        return {"session": self.sessions[session_id], "messages": self.messages.get(session_id, [])}

    def delete_session(self, session_id: str, undo_window_seconds: int = 5, library_id: str = "") -> dict[str, Any]:
        _ = undo_window_seconds
        if session_id not in self.sessions:
            raise KeyError("session_not_found")
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            raise KeyError("session_not_found")
        self.sessions.pop(session_id, None)
        self.messages.pop(session_id, None)
        return {
            "session_id": session_id,
            "deleted": True,
            "undo_deadline": "2999-01-01T00:00:00+00:00",
        }

    def restore_session(self, session_id: str, library_id: str = "") -> dict[str, Any]:
        if session_id in self.sessions:
            return {"session_id": session_id, "restored": True}
        self.sessions[session_id] = {
            "session_id": session_id,
            "title": "已恢复会话",
            "default_mode": "agent",
            "library_id": str(library_id or "").strip(),
        }
        self.messages.setdefault(session_id, [])
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
        _ = mode, provider, model, stream
        if session_id not in self.sessions:
            raise KeyError("session_not_found")
        if str(self.sessions[session_id].get("library_id", "")) != str(library_id or "").strip():
            raise KeyError("session_not_found")
        if not str(content or "").strip():
            raise ValueError("content_required")
        if not str(library_id or "").strip():
            raise ValueError("library_id_required")

        user_id = f"msg_user_{len(self.messages[session_id]) + 1}"
        assistant_id = f"msg_assistant_{len(self.messages[session_id]) + 2}"
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
        self.events[assistant_id] = self._build_events(content)
        return {"user_message_id": user_id, "assistant_message_id": assistant_id}

    def _build_events(self, content: str) -> list[dict[str, Any]]:
        lowered = str(content or "").lower()
        if "force_workspace_missing" in lowered:
            return [
                {"type": "started", "payload": {"phase": "start"}},
                {"type": "status", "payload": {"stage": "rewrite", "label": "正在改写问题"}},
                {
                    "type": "failed",
                    "payload": {
                        "error": "codex_workspace_path_missing",
                        "error_code": "codex_workspace_path_missing",
                        "backend": "codex",
                    },
                },
            ]
        if "force_failed" in lowered:
            return [
                {"type": "started", "payload": {"phase": "start"}},
                {"type": "failed", "payload": {"error": "synthetic_failure"}},
            ]
        return [
            {"type": "started", "payload": {"phase": "start"}},
            {"type": "status", "payload": {"stage": "rewrite", "label": "正在改写问题"}},
            {
                "type": "tool_call",
                "payload": {
                    "backend": "codex",
                    "step_id": "codex-1",
                    "state": "completed",
                    "summary": "weaviate.search",
                    "tool": "weaviate.search",
                },
            },
            {
                "type": "agent_item_started",
                "payload": {"backend": "codex", "step_id": "codex-1", "item": "tool"},
            },
            {
                "type": "agent_item_completed",
                "payload": {"backend": "codex", "step_id": "codex-1", "item": "tool"},
            },
            {"type": "delta", "payload": {"text": "hello"}},
            {
                "type": "completed",
                "payload": {
                    "answer": "hello world",
                    "citations": [{"id": "c1", "text": "paragraph evidence", "context": {"paragraph": {"text": "paragraph evidence"}}}],
                    "tool_trace": [
                        {
                            "backend": "codex",
                            "step_id": "codex-1",
                            "state": "completed",
                            "tool": "weaviate.search",
                            "summary": "paragraph_hits=1",
                        }
                    ],
                },
            },
        ]

    def read_events(self, message_id: str, cursor: int, wait_seconds: float = 20.0):
        _ = wait_seconds
        rows = self.events.get(message_id, [])
        if not rows:
            return [], cursor, True
        start = max(0, int(cursor))
        out = rows[start:]
        next_cursor = len(rows)
        done = any(str(x.get("type", "")) in {"completed", "failed"} for x in out) or next_cursor >= len(rows)
        if done:
            self._finalize_assistant_message(message_id, out)
        return out, next_cursor, done

    def _finalize_assistant_message(self, message_id: str, rows: list[dict[str, Any]]) -> None:
        terminal: dict[str, Any] | None = None
        for row in rows:
            t = str(row.get("type", ""))
            if t in {"completed", "failed"}:
                terminal = row
                break
        if terminal is None:
            return
        payload = terminal.get("payload") if isinstance(terminal.get("payload"), dict) else {}
        for msg_rows in self.messages.values():
            for item in msg_rows:
                if str(item.get("message_id", "")) != str(message_id):
                    continue
                if str(terminal.get("type", "")) == "completed":
                    item["status"] = "completed"
                    item["content"] = str(payload.get("answer", "") or "")
                    item["citations"] = payload.get("citations", [])
                    item["tool_trace"] = payload.get("tool_trace", [])
                else:
                    item["status"] = "failed"
                    item["error_detail"] = str(payload.get("error", "unknown_error"))
                return


def _base_views() -> dict[str, Any]:
    return {
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


class _BaseHarness:
    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._old_env: dict[str, str | None] = {}

    def setup_env(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        index_root = root / "literature_libraries"
        workspace_root = root / "workspaces"
        registry_path = root / "registry" / "registry.json"
        codex_cfg = root / "codex" / "codex_runner_config.json"

        index_root.mkdir(parents=True, exist_ok=True)
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "supply_chain").mkdir(parents=True, exist_ok=True)
        (index_root / "supply_chain.json").write_text(
            json.dumps(
                {
                    "library_id": "supply_chain",
                    "paper_count": 1,
                    "updated_at": "2026-01-01T00:00:00Z",
                    "workspace_root": str((workspace_root / "supply_chain").resolve()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        codex_cfg.parent.mkdir(parents=True, exist_ok=True)
        codex_cfg.write_text(
            json.dumps(
                {
                    "cli_command": "codex",
                    "cli_args": ["exec", "--cwd", "{workdir}", "{prompt}"],
                    "healthcheck_args": ["--version"],
                    "timeout_seconds": 120,
                    "install_command": "npm install -g @openai/codex",
                    "extra_env": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        env_map = {
            "LITERATURE_LIBRARY_INDEX_ROOT": str(index_root),
            "LITERATURE_LIBRARY_WORKSPACES_ROOT": str(workspace_root),
            "LITERATURE_LIBRARY_REGISTRY_PATH": str(registry_path),
            "LITERATURE_DEFAULT_LIBRARY_ID": "supply_chain",
            "CHAT_CODEX_CONFIG_PATH": str(codex_cfg),
        }
        for key, value in env_map.items():
            self._old_env[key] = os.environ.get(key)
            os.environ[key] = value

    def restore_env(self) -> None:
        for key, old in self._old_env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self._old_env = {}
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


class GraphChatE2EHarness:
    def __init__(self) -> None:
        self._base = _BaseHarness()
        self._server = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "GraphChatE2EHarness":
        self._base.setup_env()
        mod = load_graph_api_module()
        make_handler = mod.make_handler
        thread_server = mod.ThreadingHTTPServer
        root = Path(__file__).resolve().parent.parent
        frontend_dir = _pick_existing_dir(root / "frontend_legacy" / "graph_3d", root / "frontend" / "graph_3d")
        chat_frontend = _pick_existing_dir(root / "frontend_legacy" / "chat_embed", root / "frontend" / "chat_embed")

        handler = make_handler(
            _base_views(),
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
        self._base.restore_env()


class WorkbenchE2EHarness:
    def __init__(self) -> None:
        self._base = _BaseHarness()
        self._server = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "WorkbenchE2EHarness":
        self._base.setup_env()
        mod = load_graph_api_module()
        make_handler = mod.make_handler
        thread_server = mod.ThreadingHTTPServer
        root = Path(__file__).resolve().parent.parent
        frontend_dir = _pick_existing_dir(root / "frontend_legacy" / "graph_3d", root / "frontend" / "graph_3d")
        workbench_frontend = _pick_existing_dir(root / "frontend_legacy" / "workbench_spa", root / "frontend" / "workbench_spa")
        chat_frontend = _pick_existing_dir(root / "frontend_legacy" / "chat_embed", root / "frontend" / "chat_embed")

        handler = make_handler(
            _base_views(),
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
        self._base.restore_env()


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


def wait_for_stream_terminal(page: Any, timeout_ms: int = 45000) -> str:
    start = time.time()
    timeout_s = max(1.0, timeout_ms / 1000.0)
    while time.time() - start < timeout_s:
        assistants = page.locator("[data-testid='message-assistant']")
        count = assistants.count()
        if count > 0:
            status = (assistants.nth(count - 1).get_attribute("data-stream-status") or "").strip().lower()
            if status == "completed":
                return "completed"
            if status == "failed":
                return "failed"
        page.wait_for_timeout(100)
    raise AssertionError("stream terminal status timeout")


def wait_for_chat_ready(page: Any, timeout_ms: int = 15000) -> None:
    page.wait_for_selector("[data-testid='message-input']", timeout=timeout_ms)
    page.wait_for_selector("[data-testid='session-list']", timeout=timeout_ms)
    page.wait_for_selector("[data-testid='library-select']", timeout=timeout_ms)
