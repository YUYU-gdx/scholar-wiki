from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smj_pipeline" / "llm" / "zhipu_client.py"
_SPEC = importlib.util.spec_from_file_location("smj_pipeline_llm_zhipu_client", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load script module: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

ZhipuChatCompletionsClient = _MOD.ZhipuChatCompletionsClient
_build_zhipu_jwt = _MOD._build_zhipu_jwt


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=True).encode("utf-8")


class ZhipuClientTest(unittest.TestCase):
    def test_build_zhipu_jwt_shape(self) -> None:
        token = _build_zhipu_jwt("id123", "secret123")
        self.assertEqual(len(token.split(".")), 3)

    def test_complete_parses_string_content(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "{\"extractability_status\":\"yes\",\"paper_type\":\"quantitative_empirical\",\"extractability_reason\":\"x\",\"extractability_evidence_section\":\"Methods\",\"variable_definitions\":[],\"direct_effects\":[],\"moderations\":[],\"interactions\":[]}"
                    }
                }
            ]
        }
        client = ZhipuChatCompletionsClient(api_key="k")
        with patch.object(_MOD.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
            text = client.complete("hello")
        self.assertIn('"extractability_status"', text)

    def test_complete_parses_content_parts(self) -> None:
        payload = {
            "choices": [
                {"message": {"content": [{"type": "text", "text": "{\"a\":1}"}, {"type": "text", "text": "{\"b\":2}"}]}}
            ]
        }
        client = ZhipuChatCompletionsClient(api_key="k")
        with patch.object(_MOD.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
            text = client.complete("hello")
        self.assertEqual(text, "{\"a\":1}{\"b\":2}")

    def test_complete_raises_on_missing_choices(self) -> None:
        payload = {"not_choices": []}
        client = ZhipuChatCompletionsClient(api_key="k", max_retries=1)
        with patch.object(_MOD.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
            with self.assertRaises(ValueError):
                client.complete("hello")


if __name__ == "__main__":
    unittest.main()
