from __future__ import annotations

import unittest

from tests._e2e_helpers import GraphChatE2EHarness, ensure_playwright_ready


class GraphChatPlaywrightE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ok, reason = ensure_playwright_ready()
        if not ok:
            raise unittest.SkipTest(reason)

        from playwright.sync_api import sync_playwright

        cls._pw_manager = sync_playwright()
        cls._pw = cls._pw_manager.start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._harness = GraphChatE2EHarness().__enter__()

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

    def _goto_graph(self) -> None:
        self.page.goto(f"{self._harness.base_url}/frontend/", wait_until="domcontentloaded")
        self.page.wait_for_selector("[data-testid='graph-3d-title']")
        self.page.wait_for_selector("[data-testid='graph-3d-canvas']")
        self.page.wait_for_selector("[data-testid='graph-node']")

    def _goto_chat(self) -> None:
        self.page.goto(f"{self._harness.base_url}/frontend/chat/", wait_until="domcontentloaded")
        self.page.wait_for_selector("[data-testid='message-input']")
        self.page.wait_for_selector("[data-testid='session-item']")

    def test_graph_page_load_and_click_jump_to_chat(self) -> None:
        self._goto_graph()
        self.assertIn("3D知识图谱", self.page.locator("[data-testid='graph-3d-title']").inner_text())
        self.page.locator("[data-testid='graph-node']").first.click()
        self.page.wait_for_selector("text=文献库：供应链")
        self.page.locator("[data-testid='jump-chat-btn']").click()
        self.page.wait_for_url("**/frontend/chat/**")
        self.assertIn("from_node=", self.page.url)
        self.page.wait_for_selector("[data-testid='message-input']")

    def test_graph_page_hover_and_drag_interaction(self) -> None:
        self._goto_graph()
        first = self.page.locator("[data-testid='graph-node']").first
        first.click()
        selected_node_id = first.get_attribute("data-node-id")
        first.hover()
        self.page.wait_for_selector("text=文献库：供应链")
        active = self.page.locator("[data-testid='graph-node'].active").first
        self.assertEqual(active.get_attribute("data-node-id"), selected_node_id)

        drag_area = self.page.locator("[data-testid='graph-drag-area']")
        box = drag_area.bounding_box()
        self.assertIsNotNone(box)
        assert box is not None
        self.page.mouse.move(box["x"] + 10, box["y"] + 10)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] - 10, box["y"] + box["height"] - 10)
        self.page.mouse.up()
        self.page.wait_for_selector("text=drag-end")

    def test_chat_send_message_sse_completed_and_citations(self) -> None:
        self._goto_chat()
        self.page.locator("[data-testid='message-input']").fill("hello e2e")
        self.page.locator("[data-testid='send-btn']").click()

        self.page.wait_for_selector("[data-testid='message-user']")
        self.page.wait_for_selector("[data-testid='message-assistant']")
        self.page.wait_for_selector("[data-testid='message-assistant'][data-stream-status='completed']", timeout=45000)

        assistant_content = self.page.locator(
            "[data-testid='message-assistant'][data-stream-status='completed'] .msg-content"
        ).last
        self.assertIn("hello world", assistant_content.inner_text())

        citations = self.page.locator("[data-testid='message-citations']").last
        citations.wait_for()
        self.assertIn("c1", citations.inner_text())

    def test_return_to_graph_from_chat(self) -> None:
        self._goto_chat()
        self.page.locator("[data-testid='back-to-search-btn']").click()
        self.page.wait_for_url("**/frontend/")
        self.page.wait_for_selector("[data-testid='graph-3d-canvas']")

    def test_chat_sse_failed_terminal_event(self) -> None:
        self._goto_chat()
        self.page.locator("[data-testid='message-input']").fill("force_failed")
        self.page.locator("[data-testid='send-btn']").click()
        self.page.wait_for_selector("text=失败: synthetic_failure")

    def test_chat_request_validation_error_flow(self) -> None:
        self._goto_chat()
        result = self.page.evaluate(
            """
            async () => {
              const listResp = await fetch('/chat/sessions');
              const listed = await listResp.json();
              const sessionId = listed.sessions?.[0]?.session_id || '';
              const resp = await fetch(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  content: 'trigger validation',
                  mode: 'fast',
                  provider: 'bad_provider',
                  model: 'glm-4.5-flash',
                  stream: true
                })
              });
              const payload = await resp.json();
              return { status: resp.status, payload };
            }
            """
        )
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["payload"]["error"], "invalid_provider")


if __name__ == "__main__":
    unittest.main(verbosity=2)
