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
    """Create Chromium browser with file-access flag."""
    return playwright.chromium.launch(
        headless=True,
        args=["--allow-file-access-from-files"],
    )


def _new_page(browser: Browser) -> Page:
    """Create a new page with API_BASE injected."""
    page = browser.new_page()
    page.add_init_script(
        f'window.desktopShell = {{ getBackendUrlSync: () => "{BACKEND}" }};'
    )
    return page


def _navigate_to_settings(page: Page) -> None:
    """Navigate to the app and click the Settings button."""
    page.goto(FRONTEND)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    page.locator("button", has_text="Settings").click()
    page.wait_for_timeout(3000)


def _find_label(page: Page, label_text: str):
    """
    Find a <label> element whose text content includes `label_text`.

    WARNING: This does a substring match. For labels named "API Key",
    use _textbox_exact(page, "API Key") instead to avoid matching
    "Fast API Key" or "MinerU API Key".
    """
    return page.locator("label").filter(has_text=label_text)


def _textbox_exact(page: Page, name: str):
    """
    Find a textbox (<input>) by its EXACT accessible name.
    Use this instead of _find_label for generic names like "API Key".

    NOTE: Without exact=True, get_by_role does substring matching,
    so name="API Key" would also match "MinerU API Key" and "Fast API Key".
    """
    return page.get_by_role("textbox", name=name, exact=True)


def _textbox_exact_nth(page: Page, name: str, index: int):
    """Return the nth textbox (0-based) with exact accessible name."""
    return _textbox_exact(page, name).nth(index)


class TestSettingsPanel(unittest.TestCase):
    """E2E tests for the Settings panel."""

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

    # ── Test Case 1: Page loads with 3 category cards ──────────────────────

    def test_01_page_loads_with_three_category_cards(self):
        """Navigate to Settings and verify 3 category cards appear."""
        # Check for category titles in the DOM
        titles = ["Pipeline", "翻译", "Agent"]
        for title in titles:
            elements = self.page.locator(f"text={title}")
            self.assertGreater(
                elements.count(),
                0,
                f"Expected to find category title '{title}' on settings page",
            )
        # Verify exactly 3 save buttons (one per category card)
        save_buttons = self.page.locator("button", has_text="保存")
        self.assertEqual(
            save_buttons.count(),
            3,
            f"Expected 3 save buttons for 3 categories, found {save_buttons.count()}",
        )
        # Verify that expected fields exist for pipeline
        self.assertGreater(
            _find_label(self.page, "Fast 模式提供商").count(),
            0,
            "Pipeline: Fast 模式提供商 field missing",
        )
        # Verify that expected fields exist for translation
        self.assertGreater(
            _find_label(self.page, "翻译提供商").count(),
            0,
            "Translation: 翻译提供商 field missing",
        )
        # Verify that expected fields exist for agent settings
        self.assertGreater(
            _find_label(self.page, "当前应用 Agent").count(),
            0,
            "Agent: 当前应用 Agent field missing",
        )

    # ── Test Case 2: Pipeline change provider → auto-save loads model/api_key ──

    def test_02_pipeline_change_provider_auto_loads_fields(self):
        """Select a different provider in the 'Fast 模式提供商' dropdown and verify fields update."""
        fast_provider_select = _find_label(self.page, "Fast 模式提供商").locator(
            "select"
        )
        current_value = fast_provider_select.input_value()
        print(f"  Current fast_provider: {current_value}")

        target = "openai" if current_value != "openai" else "anthropic"
        fast_provider_select.select_option(target)
        self.page.wait_for_timeout(1500)

        self.assertEqual(
            fast_provider_select.input_value(),
            target,
            f"Expected fast_provider to be '{target}' after selection",
        )

        model_input = _find_label(self.page, "Fast 模型").locator("input")
        self.assertGreater(model_input.count(), 0, "Fast 模型 field missing")
        actual_model = model_input.input_value()
        print(f"  Fast model for {target}: '{actual_model}'")

        base_url_input = _find_label(self.page, "Fast Base URL").locator("input")
        self.assertGreater(base_url_input.count(), 0, "Fast Base URL field missing")
        actual_base = base_url_input.input_value()
        self.assertNotEqual(actual_base, "", f"Expected non-empty base_url for {target}")
        print(f"  Fast base_url for {target}: '{actual_base}'")

    # ── Test Case 3: Pipeline edit and save ────────────────────────────────

    def test_03_pipeline_edit_and_save(self):
        """Change pipeline fields, click save, and verify persistence."""
        test_model = f"test-model-{int(time.time())}"
        test_api_key = f"sk-test-{int(time.time())}"

        model_input = _find_label(self.page, "Fast 模型").locator("input")
        model_input.fill(test_model)

        api_key_input = _find_label(self.page, "Fast API Key").locator("input")
        api_key_input.fill(test_api_key)

        self.page.locator("button", has_text="保存").first.click()
        self.page.wait_for_timeout(2000)

        success_msg = self.page.locator("text=保存成功")
        self.assertGreater(
            success_msg.count(),
            0,
            "Expected '保存成功' message after saving pipeline settings",
        )

        resp = requests.get(f"{BACKEND}/settings", timeout=10)
        data = resp.json()
        pipeline = data.get("settings", {}).get("pipeline", {})
        self.assertEqual(pipeline.get("fast_model"), test_model)
        self.assertEqual(pipeline.get("fast_api_key"), test_api_key)

    # ── Test Case 4: Pipeline switch provider back and verify data preserved ──

    def test_04_pipeline_switch_provider_preserves_data(self):
        """Switch provider away, edit its data, switch back, verify original data restored."""
        fast_provider_select = _find_label(self.page, "Fast 模式提供商").locator("select")
        first_provider = fast_provider_select.input_value()
        first_model = _find_label(self.page, "Fast 模型").locator("input").input_value()
        print(f"  First provider: {first_provider}, model='{first_model}'")

        second_provider = "openai" if first_provider != "openai" else "anthropic"
        fast_provider_select.select_option(second_provider)
        self.page.wait_for_timeout(1500)

        test_model_2 = f"provider2-model-{int(time.time())}"
        _find_label(self.page, "Fast 模型").locator("input").fill(test_model_2)
        _find_label(self.page, "Fast API Key").locator("input").fill("sk-test-2")

        self.page.locator("button", has_text="保存").first.click()
        self.page.wait_for_timeout(1500)

        fast_provider_select.select_option(first_provider)
        self.page.wait_for_timeout(1500)

        restored_model = (
            _find_label(self.page, "Fast 模型").locator("input").input_value()
        )
        self.assertEqual(
            restored_model,
            first_model,
            f"Expected model '{first_model}' for provider '{first_provider}', got '{restored_model}'",
        )
        print(f"  Restored model: '{restored_model}'")

    # ── Test Case 5: Translation change provider then save ─────────────────

    def test_05_translation_change_provider_then_save(self):
        """
        Change translation provider, edit fields, save, and verify via API.
        Uses exact-name selectors for "API Key" to avoid matching "Fast API Key".
        """
        trans_provider_select = _find_label(self.page, "翻译提供商").locator("select")
        current_provider = trans_provider_select.input_value()
        print(f"  Current translation provider: {current_provider}")

        target = "openai" if current_provider != "openai" else "anthropic"
        trans_provider_select.select_option(target)
        self.page.wait_for_timeout(1500)

        self.assertEqual(trans_provider_select.input_value(), target)

        test_model = f"trans-model-{int(time.time())}"
        _find_label(self.page, "翻译模型").locator("input").fill(test_model)
        _find_label(self.page, "目标语言").locator("input").fill("ja")

        # Translation "API Key": use exact name, first one (agent is second)
        _textbox_exact_nth(self.page, "API Key", 0).fill("sk-trans-test")

        # Click save on the translation card (second save button, index 1)
        self.page.locator("button", has_text="保存").nth(1).click()
        self.page.wait_for_timeout(2000)

        success_msg = self.page.locator("text=保存成功")
        self.assertGreater(success_msg.count(), 0, "Expected success message for translation save")

        resp = requests.get(f"{BACKEND}/settings", timeout=10)
        data = resp.json()
        translation = data.get("settings", {}).get("translation", {})
        self.assertEqual(translation.get("provider"), target)
        self.assertEqual(translation.get("model"), test_model)
        self.assertEqual(translation.get("target_lang"), "ja")

    # ── Test Case 6: Translation switch provider → saved data auto-loads ───

    def test_06_translation_switch_provider_preserves_data(self):
        """Switch translation provider away and back, verify data is preserved."""
        trans_provider_select = _find_label(self.page, "翻译提供商").locator("select")
        first_provider = trans_provider_select.input_value()
        first_model = _find_label(self.page, "翻译模型").locator("input").input_value()
        print(f"  Translation first provider: {first_provider}, model='{first_model}'")

        second = "openai" if first_provider != "openai" else "anthropic"
        trans_provider_select.select_option(second)
        self.page.wait_for_timeout(1500)

        test_model_2 = f"trans2-model-{int(time.time())}"
        _find_label(self.page, "翻译模型").locator("input").fill(test_model_2)
        _textbox_exact_nth(self.page, "API Key", 0).fill("sk-trans-2")

        # Save on translation card (second card)
        self.page.locator("button", has_text="保存").nth(1).click()
        self.page.wait_for_timeout(1500)

        # Switch back to first provider
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

    # ── Test Case 7: Agent settings has provider/model/api_key fields ──────

    def test_07_agent_settings_has_correct_fields(self):
        """Verify agent settings card shows provider, model, api_key (not config_path)."""
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
        # Verify there is NO 'config_path' visible (old field)
        self.assertNotIn(
            "config_path",
            agent_card_text.lower(),
            "Agent settings should NOT show old 'config_path' field",
        )

    # ── Test Case 8: Agent change provider → base_url auto-fills ───────────

    def test_08_agent_change_provider_auto_fills_base_url(self):
        """Change agent provider and verify base_url auto-fills from preset."""
        agent_provider_select = _find_label(self.page, "供应商").locator("select")
        self.assertGreater(agent_provider_select.count(), 0, "Agent provider select not found")
        current_provider = agent_provider_select.input_value()
        print(f"  Current agent provider: {current_provider}")

        target = "openai" if current_provider != "openai" else "anthropic"
        agent_provider_select.select_option(target)
        self.page.wait_for_timeout(1500)

        self.assertEqual(agent_provider_select.input_value(), target)

        # The agent card's "Base URL": second "Base URL" label (first is translation card)
        agent_base_url = _find_label(self.page, "Base URL").nth(1).locator("input")
        actual_base_url = agent_base_url.input_value()
        self.assertNotEqual(
            actual_base_url,
            "",
            f"Expected non-empty base_url for agent provider '{target}'",
        )
        print(f"  Agent base_url for {target}: '{actual_base_url}'")

    # ── Test Case 9: Agent change current_agent → config loads ─────────────

    def test_09_agent_change_current_agent_reloads_config(self):
        """Switch the current_agent dropdown and verify fields reload."""
        agent_select = _find_label(self.page, "当前应用 Agent").locator("select")
        original_agent = agent_select.input_value()
        print(f"  Original agent: {original_agent}")

        # Fill and save current agent to establish baseline
        # NOTE: "模型" matches "Fast 模型" (nth0), "翻译模型" (nth1), "模型" (agent, nth2)
        _find_label(self.page, "模型").nth(2).locator("input").fill(
            f"agent-model-{int(time.time())}"
        )
        self.page.locator("button", has_text="保存").nth(2).click()
        self.page.wait_for_timeout(1500)

        target_agent = "codex" if original_agent != "codex" else "gemini_cli"
        agent_select.select_option(target_agent)
        self.page.wait_for_timeout(2000)

        self.assertEqual(agent_select.input_value(), target_agent)
        self.assertGreater(
            _find_label(self.page, "供应商").count(), 0, "Agent card still has 供应商"
        )

    # ── Test Case 10: Agent save → verify persisted ────────────────────────

    def test_10_agent_save_persists(self):
        """
        Save agent settings and verify they persist via API.

        IMPORTANT: The "供应商" select has an onChange handler that triggers
        applyProviderPreset, which auto-saves the provider change and replaces
        the local draft state. After switching the provider, we must wait for
        that auto-save to complete before filling other fields, or the auto-save
        response will overwrite our edits.
        """
        test_provider = "zhipu"  # Use a provider different from default to avoid collisions
        test_model = f"agent-save-model-{int(time.time())}"
        test_api_key = f"sk-agent-save-{int(time.time())}"

        agent_provider_select = _find_label(self.page, "供应商").locator("select")
        current_provider = agent_provider_select.input_value()
        print(f"  Current agent provider: {current_provider}")

        # Switch provider - this triggers applyProviderPreset which auto-saves
        # Wait for the network response to fully process before touching other fields
        agent_provider_select.select_option(test_provider)
        self.page.wait_for_timeout(2000)  # give generous time for API round-trip + React re-render

        # Verify the model value after auto-save
        # NOTE: "模型" matches "Fast 模型" (nth0), "翻译模型" (nth1), "模型" (agent, nth2)
        model_input = _find_label(self.page, "模型").nth(2).locator("input")
        model_before = model_input.input_value()
        print(f"  Model after provider switch: '{model_before}'")
        print(f"  Now filling model with: '{test_model}'")

        # Now fill our test values
        model_input.fill(test_model)

        # Agent "API Key": second textbox with exact name "API Key" (first = translation)
        agent_api_key = _textbox_exact_nth(self.page, "API Key", 1)
        agent_api_key.fill(test_api_key)

        # Debug: verify what's in the DOM before save
        print(f"  Model in input before save: '{model_input.input_value()}'")
        print(f"  API Key in input before save: '{agent_api_key.input_value()}'")

        # Click save on agent card (third save button, index 2)
        self.page.locator("button", has_text="保存").nth(2).click()
        self.page.wait_for_timeout(3000)  # generous wait for save + response + re-render

        # Verify success message
        success_msg = self.page.locator("text=保存成功")
        self.assertGreater(
            success_msg.count(), 0, "Expected success message for agent save"
        )

        # Verify model in DOM after save
        model_after = _find_label(self.page, "模型").nth(2).locator("input").input_value()
        print(f"  Model in input after save: '{model_after}'")

        # Verify via API
        resp = requests.get(f"{BACKEND}/settings", timeout=10)
        data = resp.json()
        agent = data.get("settings", {}).get("agent_settings", {})
        print(f"  API agent settings: provider={agent.get('provider')}, model={agent.get('model')}, api_key={agent.get('api_key')}")

        self.assertEqual(
            agent.get("provider"),
            test_provider,
            f"API: agent provider not persisted. Got: {agent.get('provider')}",
        )
        self.assertEqual(
            agent.get("model"),
            test_model,
            f"API: agent model not persisted. Got: {agent.get('model')}",
        )
        self.assertEqual(
            agent.get("api_key"),
            test_api_key,
            f"API: agent api_key not persisted. Got: {agent.get('api_key')}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
