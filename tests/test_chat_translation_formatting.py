from pathlib import Path

from kn_graph.config import Settings
from kn_graph.services.chat_service import ChatService


def test_translation_line_uses_translation_callout_and_escapes_html(tmp_path: Path) -> None:
    service = ChatService(Settings(data_dir=tmp_path))

    decorated = service._decorate_translation_line("<details>\n<summary>表格</summary>")

    assert decorated == (
        "> [!TRANSLATION] 译文\n"
        "> &lt;details&gt;\n"
        "> &lt;summary&gt;表格&lt;/summary&gt;"
    )


def test_translation_line_normalizes_echoed_callout_header(tmp_path: Path) -> None:
    service = ChatService(Settings(data_dir=tmp_path))
    body = "随着企业日益夸大AI应用。"

    decorated = service._decorate_translation_line(f"[!TRANSLATION] 译文 {body}")

    assert decorated == f"> [!TRANSLATION] 译文\n> {body}"


def test_translation_line_normalizes_echoed_translation_label(tmp_path: Path) -> None:
    service = ChatService(Settings(data_dir=tmp_path))
    body = "随着企业日益夸大AI应用。"

    decorated = service._decorate_translation_line(f"译文：{body}")

    assert decorated == f"> [!TRANSLATION] 译文\n> {body}"


def test_bilingual_translation_protects_math_before_provider_call(tmp_path: Path, monkeypatch) -> None:
    service = ChatService(Settings(data_dir=tmp_path))
    calls: list[str] = []

    def fake_translate_single_text(**kwargs):
        text = str(kwargs["text"])
        calls.append(text)
        return {"translated_text": f"译文：{text}", "latency_ms": 1, "provider": "fake", "model": "fake-model"}

    monkeypatch.setattr(service, "_translate_single_text", fake_translate_single_text)

    result = service.translate_markdown_bilingual(
        "This result follows $y = x + 1$ in the model.\n\n$$\nz = x^2\n$$\n\nPlain conclusion.",
        target_lang="zh",
        provider="fake",
        model="fake-model",
        api_key="key",
    )

    assert calls == [
        "This result follows __KN_FORMULA_0__ in the model.",
        "Plain conclusion.",
    ]
    text = str(result["translated_text"])
    assert "> [!TRANSLATION] 译文\n> This result follows $y = x + 1$ in the model." in text
    assert "$$\nz = x^2\n$$" in text
    assert text.count("> [!TRANSLATION] 译文") == 2


def test_single_translation_protects_math_before_provider_call(tmp_path: Path, monkeypatch) -> None:
    service = ChatService(Settings(data_dir=tmp_path))
    calls: list[str] = []

    class FakeClient:
        def complete_messages(self, *, messages, timeout_seconds):
            calls.append(str(messages[-1]["content"]))
            return f"译文：{messages[-1]['content']}"

    class FakeRegistry:
        def create_message_client(self, *, provider, model, options):
            return FakeClient()

    monkeypatch.setattr(service, "_provider_registry", lambda: FakeRegistry())
    monkeypatch.setattr(service, "get_translation_provider_config", lambda: {
        "provider": "fake",
        "model": "fake-model",
        "api_key": "key",
        "base_url": "https://example.test",
        "endpoint_url": "https://example.test/v1/chat/completions",
        "target_lang": "zh",
    })

    result = service.translate_text("Translate $a < b$ exactly.", compare_by_paragraph=False)

    assert calls == ["Translate __KN_FORMULA_0__ exactly."]
    assert result["translated_text"] == "译文：Translate $a < b$ exactly."
    assert result["formatted_text"] == "> [!TRANSLATION] 译文\n> Translate $a < b$ exactly."


def test_existing_translation_detection_accepts_new_and_old_formats(tmp_path: Path) -> None:
    service = ChatService(Settings(data_dir=tmp_path))

    assert service._is_existing_translation_block("> [!TRANSLATION] 译文\n> 已翻译")
    assert service._is_existing_translation_block('<span class="translation-label">【译文】</span>: 已翻译')
