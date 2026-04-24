from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


_CHAT_SERVICE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "chat_service.py"
_CHAT_SPEC = importlib.util.spec_from_file_location("smj_pipeline_chat_service_for_agent_free_answer_tests", _CHAT_SERVICE_PATH)
if _CHAT_SPEC is None or _CHAT_SPEC.loader is None:
    raise RuntimeError(f"Unable to load chat service module: {_CHAT_SERVICE_PATH}")
_CHAT_MOD = importlib.util.module_from_spec(_CHAT_SPEC)
sys.modules[_CHAT_SPEC.name] = _CHAT_MOD
_CHAT_SPEC.loader.exec_module(_CHAT_MOD)


class _NoRagRunner:
    def run_turn(self, query: str, workdir: str, library_id: str = "", runtime_overrides=None, on_event=None):
        _ = query, workdir, library_id, runtime_overrides
        if callable(on_event):
            on_event({"method": "item/agentMessage/delta", "params": {"delta": "我先基于常识给出回答。"}})
            on_event(
                {
                    "method": "item/completed",
                    "params": {"item": {"id": "m1", "type": "agentMessage", "text": "我先基于常识给出回答。"}},
                }
            )
            on_event({"method": "turn/completed", "params": {"turn": {"id": "t1"}}})
        return {"answer": "我先基于常识给出回答。", "thread_id": "th1", "turn_id": "t1"}


class _RunnerFactory:
    def __init__(self) -> None:
        self.runner = _NoRagRunner()

    def build(self, backend: str):
        _ = backend
        return self.runner


class ChatServiceAgentFreeAnswerTest(unittest.TestCase):
    def test_agent_no_paragraph_evidence_does_not_fail(self) -> None:
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
                message_id="msg_no_rag",
                query="解释供应链韧性与绩效关系",
                provider="codex",
                model="codex-local",
                stream=False,
                library_id="supply_chain",
            )

        self.assertIn("常识", str(result.get("answer", "")))
        self.assertEqual(result.get("citations", []), [])
        trace = result.get("retrieval_trace", {})
        self.assertFalse(bool(trace.get("paragraph_context_applied")))
        self.assertFalse(bool(trace.get("rag_tool_called")))


if __name__ == "__main__":
    unittest.main()

