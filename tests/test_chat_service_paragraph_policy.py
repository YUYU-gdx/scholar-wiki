from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
