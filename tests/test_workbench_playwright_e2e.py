from __future__ import annotations

import unittest

from tests._e2e_helpers import WorkbenchE2EHarness, ensure_playwright_ready


class WorkbenchPlaywrightE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ok, reason = ensure_playwright_ready()
        if not ok:
            raise unittest.SkipTest(reason)

        from playwright.sync_api import sync_playwright

        cls._pw_manager = sync_playwright()
        cls._pw = cls._pw_manager.start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._harness = WorkbenchE2EHarness().__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_browser"):
            cls._browser.close()
        if hasattr(cls, "_pw"):
            cls._pw.stop()
        if hasattr(cls, "_harness"):
            cls._harness.__exit__(None, None, None)

    def setUp(self) -> None:
        self.page = self._browser.new_page()

    def tearDown(self) -> None:
        self.page.close()

    def _goto_workbench(self) -> None:
        self.page.goto(f"{self._harness.base_url}/frontend/workbench/", wait_until="domcontentloaded")
        self.page.wait_for_selector("[data-testid='workbench-root']", timeout=15000)

    def _open_panel(self, panel_type: str) -> None:
        btn = {
            "chat": "[data-testid='open-panel-chat']",
            "graph": "[data-testid='open-panel-graph']",
            "import": "[data-testid='open-panel-import']",
            "search": "[data-testid='open-panel-search']",
        }[panel_type]
        self.page.locator(btn).click()
        panel_selector = {
            "chat": "[data-panel-type='chat']",
            "graph": "[data-panel-type='graph']",
            "import": "[data-panel-type='import']",
            "search": "[data-panel-type='search']",
        }[panel_type]
        deadline = self.page.evaluate("Date.now()") + 15000
        while self.page.evaluate("Date.now()") < deadline:
            if self.page.locator(panel_selector).count() > 0:
                return
            self.page.wait_for_timeout(200)
        self.fail(f"panel not created in time: {panel_type}")

    def test_workbench_default_load_success(self) -> None:
        self._goto_workbench()
        self.assertGreaterEqual(self.page.locator("[data-testid='workbench-root']").count(), 1)

    def test_open_four_panel_types_and_coexist(self) -> None:
        self._goto_workbench()
        for panel_type in ["chat", "graph", "import", "search"]:
            self._open_panel(panel_type)
        self.assertGreaterEqual(self.page.locator("[data-panel-type='chat']").count(), 1)
        self.assertGreaterEqual(self.page.locator("[data-panel-type='graph']").count(), 1)
        self.assertGreaterEqual(self.page.locator("[data-panel-type='import']").count(), 1)
        self.assertGreaterEqual(self.page.locator("[data-panel-type='search']").count(), 1)

    def test_save_layout_and_refresh_recovers(self) -> None:
        self._goto_workbench()
        for panel_type in ["chat", "graph", "import", "search"]:
            self._open_panel(panel_type)
        self.page.locator("[data-testid='save-layout-btn']").click()
        self.page.wait_for_timeout(500)
        keys = self.page.evaluate(
            """
            () => {
              const out = [];
              for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (!k) continue;
                if (k.toLowerCase().includes('workbench') || k.toLowerCase().includes('layout')) out.push(k);
              }
              return out;
            }
            """
        )
        self.assertGreaterEqual(len(keys), 1)

        self.page.reload(wait_until="domcontentloaded")
        self.page.wait_for_selector("[data-testid='workbench-root']", timeout=15000)
        self.assertGreaterEqual(self.page.locator("[data-panel-type='chat']").count(), 1)

    def test_cross_panel_link_graph_to_chat(self) -> None:
        self._goto_workbench()
        self._open_panel("graph")
        self._open_panel("chat")
        self.page.locator("[data-testid='graph-to-chat-btn']").click()
        self.page.wait_for_timeout(600)
        # Should open another chat panel carrying graph context in URL.
        chat_iframes = self.page.locator("[data-panel-type='chat'] iframe")
        self.assertGreaterEqual(chat_iframes.count(), 1)
        urls = [chat_iframes.nth(i).get_attribute("src") or "" for i in range(chat_iframes.count())]
        self.assertTrue(any("from_node=" in u for u in urls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
