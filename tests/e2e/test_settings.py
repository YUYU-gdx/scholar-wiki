"""
Playwright E2E tests for the Settings panel of the KN Graph app.

Run with:
    uv run python tests/e2e/test_settings.py

Requirements:
    - Backend running at http://127.0.0.1:8013
    - Frontend built at scholarai-workbench/dist/
"""

from __future__ import annotations

import time
import unittest

import requests
from playwright.sync_api import Page, Browser, sync_playwright

BACKEND = "http://127.0.0.1:8013"
FRONTEND = "file:///D:/Code/kn_gragh/scholarai-workbench/dist/index.html"


def _create_browser(playwright) -> Browser:
    return playwright.chromium.launch(
        headless=True,
        args=["--allow-file-access-from-files"],
    )


def _new_page(browser: Browser) -> Page:
    page = browser.new_page()
    page.add_init_script(
        f'window.desktopShell = {{ getBackendUrlSync: () => "{BACKEND}" }};'
    )
    return page


def _navigate_to_settings(page: Page) -> None:
    page.goto(FRONTEND)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    page.locator("button", has_text="Settings").click()
    page.wait_for_timeout(3000)


def _find_label(page: Page, label_text: str):
    return page.locator("label").filter(has_text=label_text)


def _textbox_exact(page: Page, name: str):
    return page.get_by_role("textbox", name=name, exact=True)


def _textbox_exact_nth(page: Page, name: str, index: int):
    return _textbox_exact(page, name).nth(index)


# ── API helpers for backup/restore ──────────────────────────────────────

def _get_settings():
    """Read full settings from the backend."""
    return requests.get(f"{BACKEND}/settings", timeout=10).json()


def _put_settings(category: str, payload: dict):
    """Write a settings category via the backend."""
    return requests.put(
        f"{BACKEND}/settings/{category}",
        json=payload,
        timeout=10,
    )


def _backup_pipeline():
    """Return pipeline settings so we can restore after a write test."""
    data = _get_settings()
    p = data.get("settings", {}).get("pipeline", {})
    return {
        "fast_provider": p.get("fast_provider", "deepseek"),
        "fast_model": p.get("fast_model", ""),
        "fast_api_key": p.get("fast_api_key", ""),
        "fast_base_url": p.get("fast_base_url", ""),
        "fast_endpoint_url": p.get("fast_endpoint_url", ""),
        "extraction_mode": p.get("extraction_mode", "fast"),
    }


def _restore_pipeline(backup: dict):
    _put_settings("pipeline", backup)


def _backup_translation():
    data = _get_settings()
    t = data.get("settings", {}).get("translation", {})
    return {
        "provider": t.get("provider", "deepseek"),
        "model": t.get("model", ""),
        "api_key": t.get("api_key", ""),
        "base_url": t.get("base_url", ""),
        "endpoint_url": t.get("endpoint_url", ""),
        "target_lang": t.get("target_lang", "zh"),
    }


def _restore_translation(backup: dict):
    _put_settings("translation", backup)


def _backup_agent():
    data = _get_settings()
    a = data.get("settings", {}).get("agent_settings", {})
    return {
        "current_agent": a.get("current_agent", "codex"),
        "provider": a.get("provider", "deepseek"),
        "model": a.get("model", ""),
        "api_key": a.get("api_key", ""),
        "base_url": a.get("base_url", ""),
    }


def _restore_agent(backup: dict):
    _put_settings("agent_settings", backup)


class TestSettingsPanel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._playwright = sync_playwright().start()
        cls._browser = _create_browser(cls._playwright)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._playwright.stop()

    def setUp(self):
        self.page = _new_page(self._browser)
        _navigate_to_settings(self.page)

    def tearDown(self):
        self.page.close()

    # ── Test Case 1: Page loads with category cards ─────────────────────

    def test_01_page_loads_with_category_cards(self):
        titles = ["Pipeline", "翻译", "Agent"]
        for title in titles:
            elements = self.page.locator(f"text={title}")
            self.assertGreater(
                elements.count(),
                0,
                f"Expected to find category title '{title}' on settings page",
            )
        save_buttons = self.page.locator("button", has_text="保存")
        self.assertEqual(
            save_buttons.count(),
            3,
            f"Expected 3 save buttons, found {save_buttons.count()}",
        )
        self.assertGreater(
            _find_label(self.page, "Fast 模式提供商").count(),
            0,
            "Pipeline: Fast 模式提供商 field missing",
        )
        self.assertGreater(
            _find_label(self.page, "翻译提供商").count(),
            0,
            "Translation: 翻译提供商 field missing",
        )
        self.assertGreater(
            _find_label(self.page, "当前应用 Agent").count(),
            0,
            "Agent: 当前应用 Agent field missing",
        )

    # ── Test Case 2: Pipeline change provider → fields auto-load ────────

    def test_02_pipeline_change_provider_auto_loads_fields(self):
        fast_provider_select = _find_label(self.page, "Fast 模式提供商").locator("select")
        current_value = fast_provider_select.input_value()
        print(f"  Current fast_provider: {current_value}")

        # Switch to a different provider that has preset data (openai or anthropic)
        target = "openai" if current_value != "openai" else "anthropic"
        fast_provider_select.select_option(target)
        self.page.wait_for_timeout(1500)

        self.assertEqual(fast_provider_select.input_value(), target)

        model_input = _find_label(self.page, "Fast 模型").locator("input")
        self.assertGreater(model_input.count(), 0, "Fast 模型 field missing")
        actual_model = model_input.input_value()
        print(f"  Fast model for {target}: '{actual_model}'")

        base_url_input = _find_label(self.page, "Fast Base URL").locator("input")
        self.assertGreater(base_url_input.count(), 0, "Fast Base URL field missing")
        actual_base = base_url_input.input_value()
        self.assertNotEqual(actual_base, "", f"Expected non-empty base_url for {target}")
        print(f"  Fast base_url for {target}: '{actual_base}'")

        # Switch back to original provider — no save needed, just verify UI
        fast_provider_select.select_option(current_value)
        self.page.wait_for_timeout(1500)

    # ── Test Case 3: Pipeline edit and save (restores original after) ───

    def test_03_pipeline_edit_and_save(self):
        backup = _backup_pipeline()
        try:
            model_input = _find_label(self.page, "Fast 模型").locator("input")
            api_key_input = _find_label(self.page, "Fast API Key").locator("input")

            model_input.fill("deepseek-v4-flash")
            api_key_input.fill("sk-pipe-ds")

            self.page.locator("button", has_text="保存").first.click()
            self.page.wait_for_timeout(2000)

            success_msg = self.page.locator("text=保存成功")
            self.assertGreater(
                success_msg.count(),
                0,
                "Expected '保存成功' message after saving pipeline settings",
            )

            data = _get_settings()
            pipeline = data.get("settings", {}).get("pipeline", {})
            self.assertEqual(pipeline.get("fast_model"), "deepseek-v4-flash")
            self.assertEqual(pipeline.get("fast_api_key"), "sk-pipe-ds")
        finally:
            _restore_pipeline(backup)

    # ── Test Case 4: Pipeline switch provider preserves data (no write) ─

    def test_04_pipeline_switch_provider_preserves_data(self):
        fast_provider_select = _find_label(self.page, "Fast 模式提供商").locator("select")
        first_provider = fast_provider_select.input_value()
        first_model = _find_label(self.page, "Fast 模型").locator("input").input_value()
        print(f"  First provider: {first_provider}, model='{first_model}'")

        # Switch to a second provider, verify its fields load, then switch
        # back WITHOUT saving — original data must survive in the UI.
        second_provider = "openai" if first_provider != "openai" else "anthropic"
        fast_provider_select.select_option(second_provider)
        self.page.wait_for_timeout(1500)

        # Just verify the UI updated (fields changed for the new provider)
        second_model = _find_label(self.page, "Fast 模型").locator("input").input_value()
        print(f"  Second provider model: '{second_model}'")
        # The second provider's model may be empty or a preset — either is fine
        # as long as the UI responded to the switch.

        # Switch back without saving
        fast_provider_select.select_option(first_provider)
        self.page.wait_for_timeout(1500)

        restored_model = (
            _find_label(self.page, "Fast 模型").locator("input").input_value()
        )
        self.assertEqual(
            restored_model,
            first_model,
            f"Expected model '{first_model}' back, got '{restored_model}'",
        )
        print(f"  Restored model: '{restored_model}'")

    # ── Test Case 5: Translation change provider then save (restores) ───

    def test_05_translation_change_provider_then_save(self):
        backup = _backup_translation()
        try:
            trans_provider_select = _find_label(self.page, "翻译提供商").locator("select")
            current_provider = trans_provider_select.input_value()
            print(f"  Current translation provider: {current_provider}")

            target = "openai" if current_provider != "openai" else "anthropic"
            trans_provider_select.select_option(target)
            self.page.wait_for_timeout(1500)

            self.assertEqual(trans_provider_select.input_value(), target)

            _find_label(self.page, "翻译模型").locator("input").fill("gpt-4o-mini")
            _find_label(self.page, "目标语言").locator("input").fill("ja")
            _textbox_exact_nth(self.page, "API Key", 0).fill("sk-trans-test")

            self.page.locator("button", has_text="保存").nth(1).click()
            self.page.wait_for_timeout(2000)

            success_msg = self.page.locator("text=保存成功")
            self.assertGreater(success_msg.count(), 0, "Expected success message for translation save")

            data = _get_settings()
            translation = data.get("settings", {}).get("translation", {})
            self.assertEqual(translation.get("provider"), target)
            self.assertEqual(translation.get("model"), "gpt-4o-mini")
            self.assertEqual(translation.get("target_lang"), "ja")
        finally:
            _restore_translation(backup)

    # ── Test Case 6: Translation switch provider preserves data (no write)

    def test_06_translation_switch_provider_preserves_data(self):
        trans_provider_select = _find_label(self.page, "翻译提供商").locator("select")
        first_provider = trans_provider_select.input_value()
        first_model = _find_label(self.page, "翻译模型").locator("input").input_value()
        print(f"  Translation first provider: {first_provider}, model='{first_model}'")

        second = "openai" if first_provider != "openai" else "anthropic"
        trans_provider_select.select_option(second)
        self.page.wait_for_timeout(1500)

        # Switch back without saving
        trans_provider_select.select_option(first_provider)
        self.page.wait_for_timeout(1500)

        restored_model = (
            _find_label(self.page, "翻译模型").locator("input").input_value()
        )
        self.assertEqual(
            restored_model,
            first_model,
            f"Translation: expected model '{first_model}' back, got '{restored_model}'",
        )
        print(f"  Restored translation model: '{restored_model}'")

    # ── Test Case 7: Agent settings has expected fields ─────────────────

    def test_07_agent_settings_has_correct_fields(self):
        self.assertGreater(
            _find_label(self.page, "当前应用 Agent").count(),
            0,
            "Agent settings: '当前应用 Agent' missing",
        )
        self.assertGreater(
            _find_label(self.page, "供应商").count(),
            0,
            "Agent settings: '供应商' field missing",
        )
        agent_card_text = self.page.text_content("body")
        self.assertIn("模型", agent_card_text, "Agent card: '模型' field missing")
        self.assertIn("API Key", agent_card_text, "Agent card: 'API Key' field missing")
        self.assertNotIn(
            "config_path",
            agent_card_text.lower(),
            "Agent settings should NOT show old 'config_path' field",
        )

    # ── Test Case 8: Agent change provider → base_url auto-fills ────────

    def test_08_agent_change_provider_auto_fills_base_url(self):
        agent_provider_select = _find_label(self.page, "供应商").locator("select")
        self.assertGreater(agent_provider_select.count(), 0, "Agent provider select not found")
        current_provider = agent_provider_select.input_value()
        print(f"  Current agent provider: {current_provider}")

        target = "openai" if current_provider != "openai" else "anthropic"
        agent_provider_select.select_option(target)
        self.page.wait_for_timeout(1500)

        self.assertEqual(agent_provider_select.input_value(), target)

        agent_base_url = _find_label(self.page, "Base URL").nth(1).locator("input")
        actual_base_url = agent_base_url.input_value()
        self.assertNotEqual(
            actual_base_url,
            "",
            f"Expected non-empty base_url for agent provider '{target}'",
        )
        print(f"  Agent base_url for {target}: '{actual_base_url}'")

    # ── Test Case 9: Agent change current_agent → config loads ──────────

    def test_09_agent_change_current_agent_reloads_config(self):
        agent_select = _find_label(self.page, "当前应用 Agent").locator("select")
        original_agent = agent_select.input_value()
        print(f"  Original agent: {original_agent}")

        target_agent = "codex" if original_agent != "codex" else "gemini_cli"
        agent_select.select_option(target_agent)
        self.page.wait_for_timeout(2000)

        self.assertEqual(agent_select.input_value(), target_agent)
        self.assertGreater(
            _find_label(self.page, "供应商").count(), 0, "Agent card still has 供应商"
        )

    # ── Test Case 10: Agent save → verify persisted (restores after) ────

    def test_10_agent_save_persists(self):
        backup = _backup_agent()
        try:
            agent_provider_select = _find_label(self.page, "供应商").locator("select")
            current_provider = agent_provider_select.input_value()
            print(f"  Current agent provider: {current_provider}")

            # Use zhipu / glm-4 which matches the real config
            agent_provider_select.select_option("zhipu")
            self.page.wait_for_timeout(2000)

            model_input = _find_label(self.page, "模型").nth(2).locator("input")
            model_before = model_input.input_value()
            print(f"  Model after provider switch: '{model_before}'")

            model_input.fill("glm-4")
            _textbox_exact_nth(self.page, "API Key", 1).fill("sk-cx")

            print(f"  Model in input before save: '{model_input.input_value()}'")
            print(f"  API Key in input before save: '{_textbox_exact_nth(self.page, 'API Key', 1).input_value()}'")

            self.page.locator("button", has_text="保存").nth(2).click()
            self.page.wait_for_timeout(3000)

            success_msg = self.page.locator("text=保存成功")
            self.assertGreater(
                success_msg.count(), 0, "Expected success message for agent save"
            )

            data = _get_settings()
            agent = data.get("settings", {}).get("agent_settings", {})
            print(f"  API agent settings: provider={agent.get('provider')}, model={agent.get('model')}")

            self.assertEqual(agent.get("provider"), "zhipu")
            self.assertEqual(agent.get("model"), "glm-4")
            self.assertEqual(agent.get("api_key"), "sk-cx")
        finally:
            _restore_agent(backup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
