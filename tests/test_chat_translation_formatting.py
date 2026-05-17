from __future__ import annotations

import tempfile
import time
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService


class _FakeMessageClient:
    def complete_messages(self, messages, timeout_seconds=90):
        _ = messages, timeout_seconds
        return "你好世界"


class _FakeRegistry:
    def __init__(self, config_path=None):
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
            self.assertIn('class="translation-label"', str(out["formatted_text"]))
            self.assertIn("【译文】", str(out["formatted_text"]))

    def test_default_provider_registry_uses_bundle_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = ChatService(Settings(data_dir=Path(tmp)))
            calls: list[object] = []

            class _TrackingRegistry(_FakeRegistry):
                def __init__(self, config_path=None):
                    calls.append(config_path)
                    super().__init__(config_path=config_path)

            with patch("kn_graph.services.chat_service.ProviderRegistry", _TrackingRegistry):
                svc.translate_text(text="hello", api_key="sk-test", compare_by_paragraph=False)

            self.assertEqual(calls, [None])

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

    def test_failed_translation_job_writes_diagnostic_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            svc = ChatService(Settings(data_dir=data_dir))

            def _fail_translate(**kwargs):
                _ = kwargs
                raise RuntimeError("provider_timeout")

            with patch.object(svc, "_translate_single_text", side_effect=_fail_translate):
                submit = svc.submit_markdown_translation_job(
                    "A\n\nB",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    endpoint_url="https://example.test/v1/chat/completions",
                )
                job_id = str(submit.get("job_id", "") or "")
                status = {}
                for _ in range(60):
                    status = svc.get_translation_job(job_id)
                    if str(status.get("status", "")) == "failed":
                        break
                    time.sleep(0.03)

            self.assertEqual(status.get("status"), "failed")
            log_path = data_dir / "logs" / "translation_failures.jsonl"
            self.assertTrue(log_path.exists())
            rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["job_id"], job_id)
            self.assertEqual(rows[0]["phase"], "job_run")
            self.assertEqual(rows[0]["provider"], "deepseek")
            self.assertEqual(rows[0]["model"], "deepseek-v4-flash")
            self.assertEqual(rows[0]["error"], "provider_timeout")
            self.assertNotIn("api_key", rows[0])

    def test_markdown_compare_skips_existing_notes_and_translations(self) -> None:
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

            source = (
                "Para one.\n\n"
                "<span class=\"translation-label\">【译文】</span>: old text\n\n"
                "> [!NOTE] Reader Note\n"
                "> Note ID: abc\n"
                "> Quote:\n"
                "> foo\n\n"
                "Para two.\n\n"
                "Translation: already translated"
            )
            with patch.object(svc, "_translate_single_text", side_effect=_fake_translate_single_text) as m:
                out = svc.translate_text(text=source, compare_by_paragraph=True)
            rendered = str(out.get("formatted_text", "") or "")
            self.assertIn("ZH:Para one.", rendered)
            self.assertIn("ZH:Para two.", rendered)
            self.assertNotIn("ZH:Translation: already translated", rendered)
            self.assertNotIn("ZH:【译文】:", rendered)
            self.assertEqual(m.call_count, 2)

    def test_markdown_compare_skips_reference_h1_section(self) -> None:
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

            source = (
                "# Intro\n\n"
                "Main body.\n\n"
                "# References\n\n"
                "[1] Foo Bar.\n\n"
                "Another ref line.\n\n"
                "# Appendix\n\n"
                "Appendix body."
            )
            with patch.object(svc, "_translate_single_text", side_effect=_fake_translate_single_text) as m:
                out = svc.translate_text(text=source, compare_by_paragraph=True)
            rendered = str(out.get("formatted_text", "") or "")
            self.assertIn("ZH:# Intro", rendered)
            self.assertIn("ZH:Main body.", rendered)
            self.assertNotIn("ZH:[1] Foo Bar.", rendered)
            self.assertNotIn("ZH:Another ref line.", rendered)
            self.assertIn("ZH:# Appendix", rendered)
            self.assertIn("ZH:Appendix body.", rendered)
            self.assertEqual(m.call_count, 4)


if __name__ == "__main__":
    unittest.main()
