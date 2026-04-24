from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


_CHAT_SERVICE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "chat_service.py"
_CHAT_SPEC = importlib.util.spec_from_file_location("smj_pipeline_chat_service_for_paragraph_policy_tests", _CHAT_SERVICE_PATH)
if _CHAT_SPEC is None or _CHAT_SPEC.loader is None:
    raise RuntimeError(f"Unable to load chat service module: {_CHAT_SERVICE_PATH}")
_CHAT_MOD = importlib.util.module_from_spec(_CHAT_SPEC)
sys.modules[_CHAT_SPEC.name] = _CHAT_MOD
_CHAT_SPEC.loader.exec_module(_CHAT_MOD)


class _CaptureModelRouter:
    def __init__(self) -> None:
        self.complete_calls: list[list[dict[str, str]]] = []

    def complete(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90) -> str:
        _ = provider, model, timeout_seconds
        self.complete_calls.append(messages)
        return "ok"

    def stream(self, provider: str, model: str, messages: list[dict[str, str]], timeout_seconds: int = 90):
        _ = provider, model, messages, timeout_seconds
        yield "ok"


class _CaptureCodexRunner:
    def __init__(self, answer: str = "agent answer") -> None:
        self.calls: list[dict[str, str]] = []
        self.answer = answer

    def run_turn(
        self,
        query: str,
        workdir: str,
        library_id: str = "",
        runtime_overrides=None,
        on_event=None,
    ) -> dict[str, str]:
        _ = library_id, runtime_overrides
        self.calls.append({"query": query, "workdir": workdir, "runtime_overrides": runtime_overrides or {}})
        if callable(on_event):
            on_event(
                {
                    "method": "item/started",
                    "params": {"item": {"id": "i1", "type": "mcpToolCall", "tool": "rag_search"}},
                }
            )
            on_event(
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "id": "i1",
                            "type": "mcpToolCall",
                            "tool": "rag_search",
                            "status": "completed",
                            "arguments": {"query": query, "top_k": 4},
                            "result": {
                                "structuredContent": {
                                    "paragraph_hits": [
                                        {"id": "p1", "title": "paper-1", "text": "Paragraph evidence from rag_search"}
                                    ]
                                }
                            },
                        }
                    },
                }
            )
            on_event({"method": "item/agentMessage/delta", "params": {"delta": self.answer}})
            on_event(
                {
                    "method": "item/completed",
                    "params": {"item": {"id": "i2", "type": "agentMessage", "text": self.answer}},
                }
            )
            on_event({"method": "turn/completed", "params": {"turn": {"id": "t1"}}})
        return {"answer": self.answer, "thread_id": "th1", "turn_id": "t1"}


class _CaptureRunnerFactory:
    def __init__(self, runner: _CaptureCodexRunner) -> None:
        self.runner = runner

    def build(self, backend: str):
        _ = backend
        return self.runner


class ChatServiceParagraphPolicyTest(unittest.TestCase):
    def test_fast_mode_uses_paragraph_context_only(self) -> None:
        def _literature_search(query: str, top_k: int, library_id: str = "") -> dict[str, object]:
            _ = query, top_k, library_id
            return {
                "keyword_hits": [
                    {
                        "id": "s1",
                        "level": "sentence",
                        "text": "Sentence level text should not be used",
                        "context": {
                            "paragraph": {"text": "Paragraph context A"},
                            "sentence": {"text": "Sentence level text should not be used"},
                        },
                    }
                ],
                "rag_hits": [],
                "merged_hits": [],
            }

        service = _CHAT_MOD.ChatService(
            literature_search_fn=_literature_search,
            graph_search_fn=lambda query, top_k: [],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
        )
        service._models = _CaptureModelRouter()
        service._rewrite_query = lambda query, provider, model: query

        result = service._run_fast(
            message_id="msg_test_fast_para_only",
            query="q",
            provider="glm",
            model="glm-4.5-flash",
            stream=False,
            library_id="lib_a",
        )

        self.assertTrue(bool(result["retrieval_trace"].get("paragraph_context_applied")))
        self.assertEqual(int(result["retrieval_trace"].get("dropped_non_paragraph_count", 0)), 0)
        captured = service._models.complete_calls[-1]
        user_prompt = captured[-1]["content"]
        self.assertIn("Paragraph context A", user_prompt)
        self.assertNotIn("Sentence level text should not be used", user_prompt)

    def test_fast_mode_fails_when_no_paragraph_context(self) -> None:
        service = _CHAT_MOD.ChatService(
            literature_search_fn=lambda query, top_k, library_id="": {
                "keyword_hits": [{"id": "s_only", "level": "sentence", "text": "Sentence only"}],
                "rag_hits": [],
                "merged_hits": [],
            },
            graph_search_fn=lambda query, top_k: [{"id": "g1", "text": "Graph evidence"}],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
        )
        service._models = _CaptureModelRouter()
        service._rewrite_query = lambda query, provider, model: query

        with self.assertRaises(RuntimeError) as ctx:
            service._run_fast(
                message_id="msg_test_fast_para_required",
                query="q",
                provider="glm",
                model="glm-4.5-flash",
                stream=False,
                library_id="lib_a",
            )
        self.assertIn("paragraph_context_unavailable", str(ctx.exception))

    def test_agent_backend_unavailable_does_not_fallback(self) -> None:
        service = _CHAT_MOD.ChatService(
            literature_search_fn=lambda query, top_k, library_id="": {"keyword_hits": [], "rag_hits": [], "merged_hits": []},
            graph_search_fn=lambda query, top_k: [],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
            agent_backend="hermes",
        )

        with self.assertRaises(RuntimeError) as ctx:
            service._run_agent(
                message_id="msg_test_agent_backend",
                query="q",
                provider="glm",
                model="glm-4.5-flash",
                stream=False,
                library_id="lib_a",
            )
        self.assertIn("agent_backend_unavailable:hermes", str(ctx.exception))

    def test_codex_backend_workspace_missing_does_not_fallback(self) -> None:
        service = _CHAT_MOD.ChatService(
            literature_search_fn=lambda query, top_k, library_id="": {"keyword_hits": [], "rag_hits": [], "merged_hits": []},
            graph_search_fn=lambda query, top_k: [],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
            library_workspace_resolver_fn=lambda _library_id: "",
            agent_backend="codex",
        )
        with self.assertRaises(RuntimeError) as ctx:
            service._run_agent(
                message_id="msg_test_agent_codex",
                query="q",
                provider="codex",
                model="codex-local",
                stream=False,
                library_id="lib_a",
            )
        self.assertIn("codex_workspace_path_missing", str(ctx.exception))

    def test_workspace_missing_failed_event_is_structured(self) -> None:
        service = _CHAT_MOD.ChatService(
            literature_search_fn=lambda query, top_k, library_id="": {"keyword_hits": [], "rag_hits": [], "merged_hits": []},
            graph_search_fn=lambda query, top_k: [],
            paper_get_fn=lambda _: None,
            variable_get_fn=lambda _: None,
            library_workspace_resolver_fn=lambda _library_id: "",
            agent_backend="codex",
        )
        session = service.create_session(title="x", default_mode="agent", library_id="lib_missing")
        payload = service.submit_message(
            session_id=str(session.get("session_id", "")),
            content="hello",
            mode="agent",
            provider="codex",
            model="codex-local",
            stream=True,
            library_id="lib_missing",
        )
        message_id = str(payload.get("assistant_message_id", ""))
        cursor = 0
        failed_payload = None
        for _ in range(50):
            events, cursor, done = service.read_events(message_id=message_id, cursor=cursor, wait_seconds=0.2)
            for item in events:
                if str(item.get("type", "")) == "failed":
                    failed_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                    break
            if failed_payload or done:
                break
        self.assertIsNotNone(failed_payload)
        assert isinstance(failed_payload, dict)
        self.assertEqual(str(failed_payload.get("error_code", "")), "codex_workspace_path_missing")
        self.assertEqual(str(failed_payload.get("backend", "")), "codex")
        self.assertEqual(str(failed_payload.get("library_id", "")), "lib_missing")
        self.assertIn("codex_workspace_path_missing", str(failed_payload.get("error", "")))

    def test_codex_agent_consumes_app_server_items_and_returns_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _CaptureCodexRunner(answer="agent answer from codex")
            service = _CHAT_MOD.ChatService(
                literature_search_fn=lambda query, top_k, library_id="": {"keyword_hits": [], "rag_hits": [], "merged_hits": []},
                graph_search_fn=lambda query, top_k: [],
                paper_get_fn=lambda _: None,
                variable_get_fn=lambda _: None,
                library_workspace_resolver_fn=lambda _library_id: tmpdir,
                agent_backend="codex",
            )
            service._runner_factory = _CaptureRunnerFactory(runner)

            result = service._run_agent(
                message_id="msg_test_tool_agent",
                query="测试问题：供应链韧性与绩效",
                provider="codex",
                model="codex-local",
                stream=False,
                library_id="supply_chain",
            )

            self.assertIn("agent answer from codex", str(result.get("answer", "")))
            self.assertEqual(len(result.get("citations", [])), 1)
            self.assertGreaterEqual(len(result.get("tool_trace", [])), 1)
            first_trace = result.get("tool_trace", [])[0]
            self.assertEqual(str(first_trace.get("kind", "")), "tool")
            self.assertTrue(str(first_trace.get("args_preview", "")).strip())
            self.assertTrue(str(first_trace.get("output_summary", "")).strip())
            self.assertEqual(runner.calls[0]["query"], "测试问题：供应链韧性与绩效")
            self.assertTrue(isinstance(runner.calls[0].get("runtime_overrides"), dict))

    def test_codex_agent_allows_smalltalk_without_paragraph_citation(self) -> None:
        class _SmalltalkRunner:
            def run_turn(self, query: str, workdir: str, library_id: str = "", runtime_overrides=None, on_event=None):
                _ = query, workdir, library_id, runtime_overrides
                if callable(on_event):
                    on_event({"method": "item/agentMessage/delta", "params": {"delta": "你好，我在。"}})
                    on_event({"method": "item/completed", "params": {"item": {"id": "m1", "type": "agentMessage", "text": "你好，我在。"}}})
                    on_event({"method": "turn/completed", "params": {"turn": {"id": "t1"}}})
                return {"answer": "你好，我在。", "thread_id": "th1", "turn_id": "t1"}

        class _RunnerFactory:
            def __init__(self) -> None:
                self.runner = _SmalltalkRunner()

            def build(self, backend: str):
                _ = backend
                return self.runner

        with tempfile.TemporaryDirectory() as tmpdir:
            service = _CHAT_MOD.ChatService(
                literature_search_fn=lambda query, top_k, library_id="": {"keyword_hits": [], "rag_hits": [], "merged_hits": []},
                graph_search_fn=lambda query, top_k: [],
                paper_get_fn=lambda _: None,
                variable_get_fn=lambda _: None,
                library_workspace_resolver_fn=lambda _library_id: tmpdir,
                agent_backend="codex",
            )
            service._runner_factory = _RunnerFactory()
            result = service._run_agent(
                message_id="msg_smalltalk",
                query="你好",
                provider="codex",
                model="codex-local",
                stream=False,
                library_id="supply_chain",
            )
            self.assertEqual(str(result.get("answer", "")), "你好，我在。")
            self.assertEqual(result.get("citations", []), [])
            self.assertTrue(bool(result.get("retrieval_trace", {}).get("smalltalk_bypass")))


if __name__ == "__main__":
    unittest.main()
