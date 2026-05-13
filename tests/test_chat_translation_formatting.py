from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService


class _FakeMessageClient:
    def complete_messages(self, messages, timeout_seconds=90):
        _ = messages, timeout_seconds
        return "你好世界"


class _FakeRegistry:
    def __init__(self, config_path):
        _ = config_path

    def create_message_client(self, provider, model, options):
        _ = provider, model, options
        return _FakeMessageClient()


class ChatTranslationFormattingTest(unittest.TestCase):
    def test_plain_translation_has_green_prefix_markup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = ChatService(Settings(data_dir=Path(tmp)))
            with patch("kn_graph.services.chat_service.ProviderRegistry", _FakeRegistry):
                out = svc.translate_text(text="hello", compare_by_paragraph=False)
            self.assertEqual(out["translated_text"], "你好世界")
            self.assertIn("color:#16a34a", out["formatted_text"])
            self.assertIn("译文", out["formatted_text"])

    def test_markdown_compare_translation_per_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = ChatService(Settings(data_dir=Path(tmp)))

            def _fake_translate_single_text(**kwargs):
                text = str(kwargs.get("text", "") or "")
                return {
                    "translated_text": f"ZH:{text}",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "target_lang": "zh",
                    "latency_ms": 1,
                }

            with patch.object(svc, "_translate_single_text", side_effect=_fake_translate_single_text):
                out = svc.translate_text(
                    text="# Title\n\nFirst paragraph.\n\n```python\nprint('x')\n```\n\nSecond paragraph.",
                    compare_by_paragraph=True,
                )
            rendered = str(out.get("formatted_text", "") or "")
            self.assertTrue(bool(out.get("compare_by_paragraph")))
            self.assertIn("# Title", rendered)
            self.assertIn("ZH:# Title", rendered)
            self.assertIn("First paragraph.", rendered)
            self.assertIn("ZH:First paragraph.", rendered)
            self.assertIn("```python\nprint('x')\n```", rendered)
            self.assertNotIn("ZH:```python", rendered)
            self.assertIn("Second paragraph.", rendered)
            self.assertIn("ZH:Second paragraph.", rendered)

    def test_submit_translation_job_runs_to_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = ChatService(Settings(data_dir=Path(tmp)))

            def _fake_translate_single_text(**kwargs):
                text = str(kwargs.get("text", "") or "")
                return {
                    "translated_text": f"ZH:{text}",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "target_lang": "zh",
                    "latency_ms": 1,
                }

            with patch.object(svc, "_translate_single_text", side_effect=_fake_translate_single_text):
                submit = svc.submit_markdown_translation_job("A\n\nB")
                job_id = str(submit.get("job_id", "") or "")
                self.assertTrue(bool(job_id))
                status = {}
                for _ in range(60):
                    status = svc.get_translation_job(job_id)
                    if str(status.get("status", "")) in {"completed", "failed"}:
                        break
                    time.sleep(0.03)
                self.assertEqual(status.get("status"), "completed")
                self.assertEqual(int(status.get("progress", 0) or 0), 100)
                result = status.get("result") if isinstance(status.get("result"), dict) else {}
                self.assertIn("ZH:A", str(result.get("translated_text", "") or ""))


if __name__ == "__main__":
    unittest.main()
