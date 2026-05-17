from __future__ import annotations

from typing import Any
import unittest

from kn_graph.services.chat_legacy import ChatService


class _FakeRunner:
    def __init__(self) -> None:
        self.run_turn_thread_ids: list[str] = []
        self.next_real_thread_id = "real-session-1"

    def thread_start(
        self,
        workdir: str,
        library_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = workdir, library_id, runtime_overrides
        return {"thread": {"id": "placeholder-session"}}

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        thread_id: str = "",
        runtime_overrides: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> dict[str, Any]:
        _ = query, workdir, library_id, runtime_overrides, on_event
        self.run_turn_thread_ids.append(thread_id)
        return {
            "answer": "ok",
            "thread_id": self.next_real_thread_id,
            "turn_id": self.next_real_thread_id,
        }


class _FakeRunnerFactory:
    def __init__(self, runner: _FakeRunner) -> None:
        self.runner = runner

    def build(self, backend: str) -> _FakeRunner:
        _ = backend
        return self.runner


class ChatSessionAliasTest(unittest.TestCase):
    def test_reuses_real_agent_thread_after_placeholder_session_resolves(self) -> None:
        runner = _FakeRunner()
        service = ChatService(
            literature_search_fn=lambda q, k, library_id="": {},
            graph_search_fn=lambda q, k: [],
            paper_get_fn=lambda paper_id: None,
            variable_get_fn=lambda variable_id: None,
            library_workspace_resolver_fn=lambda library_id: "",
        )
        service._ChatService__runner_factory = _FakeRunnerFactory(runner)
        service._agent_backend = "claude_code"

        created = service.create_session(title="x", library_id="lib1")
        session_id = str(created["session_id"])

        first = service._run_agent(
            message_id="msg1",
            query="hello",
            provider="",
            model="",
            stream=False,
            library_id="lib1",
            thread_id=session_id,
        )
        second = service._run_agent(
            message_id="msg2",
            query="again",
            provider="",
            model="",
            stream=False,
            library_id="lib1",
            thread_id=session_id,
        )

        self.assertEqual("real-session-1", first["retrieval_trace"]["thread_id"])
        self.assertEqual("real-session-1", second["retrieval_trace"]["thread_id"])
        self.assertEqual(["placeholder-session", "real-session-1"], runner.run_turn_thread_ids)


if __name__ == "__main__":
    unittest.main()
