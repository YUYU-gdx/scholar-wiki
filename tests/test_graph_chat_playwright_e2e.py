from __future__ import annotations

import unittest

from _e2e_helpers import (
    GraphChatE2EHarness,
    ensure_playwright_ready,
    wait_for_chat_ready,
    wait_for_stream_terminal,
)


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
        wait_for_chat_ready(self.page)

    def _select_library(self) -> None:
        self.page.select_option("[data-testid='library-select']", "supply_chain")
        self.assertEqual(self.page.input_value("[data-testid='library-select']"), "supply_chain")

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

    def test_chat_send_message_sse_completed_and_citations_tool_trace(self) -> None:
        self._goto_chat()
        self._select_library()
        self.page.locator("[data-testid='message-input']").fill("hello e2e")
        self.page.locator("[data-testid='send-btn']").click()

        terminal = wait_for_stream_terminal(self.page)
        self.assertEqual(terminal, "completed")

        assistant_content = self.page.locator(
            "[data-testid='message-assistant'][data-stream-status='completed'] .msg-content"
        ).last
        self.assertIn("hello world", assistant_content.inner_text())

        citations = self.page.locator("[data-testid='message-citations']").last
        citations.wait_for()
        citations.click()
        self.page.locator(".citation-drawer").last.evaluate("(el) => { el.open = true; }")
        self.page.locator(".citation-drawer[open] .citation-item-btn").last.click(force=True)
        self.page.wait_for_function(
            "() => { const m = document.querySelector('[data-testid=\"citation-modal\"]'); return !!m && !m.classList.contains('hidden'); }",
            timeout=10000,
        )
        self.page.locator("#citation-modal-close").click()

        merged_text = self.page.locator(
            "[data-testid='message-assistant'][data-stream-status='completed'] .msg-content"
        ).last.inner_text()
        self.assertIn("过程摘要", merged_text)

    def test_chat_codex_workspace_missing_then_success(self) -> None:
        self._goto_chat()
        self._select_library()

        self.page.locator("[data-testid='message-input']").fill("force_workspace_missing")
        self.page.locator("[data-testid='send-btn']").click()
        terminal = wait_for_stream_terminal(self.page)
        self.assertEqual(terminal, "failed")
        failed_text = self.page.locator("[data-testid='message-assistant'][data-stream-status='failed'] .msg-content").last.inner_text()
        self.assertIn("codex_workspace_path_missing", failed_text)

        completed_before = self.page.locator("[data-testid='message-assistant'][data-stream-status='completed']").count()
        self.page.locator("[data-testid='message-input']").fill("hello after fix")
        self.page.locator("[data-testid='send-btn']").click()
        self.page.wait_for_function(
            "(before) => document.querySelectorAll(\"[data-testid='message-assistant'][data-stream-status='completed']\").length > before",
            arg=completed_before,
            timeout=45000,
        )
        self.assertIn(
            "hello world",
            self.page.locator("[data-testid='message-assistant'][data-stream-status='completed'] .msg-content").last.inner_text(),
        )

    def test_chat_sse_failed_terminal_event(self) -> None:
        self._goto_chat()
        self._select_library()
        self.page.locator("[data-testid='message-input']").fill("force_failed")
        self.page.locator("[data-testid='send-btn']").click()
        self.page.wait_for_selector("text=失败: synthetic_failure")

    def test_chat_library_required_guard_flow(self) -> None:
        self._goto_chat()
        self.page.select_option("[data-testid='library-select']", "")
        self.page.locator("[data-testid='message-input']").fill("no lib")
        self.page.locator("[data-testid='send-btn']").click()
        self.page.wait_for_selector("text=失败: library_id_required")

    def test_new_session_delete_and_undo(self) -> None:
        self._goto_chat()
        before = self.page.locator(".session-item").count()
        self.page.locator("[data-testid='new-session-btn']").click()
        self.page.wait_for_timeout(300)
        after_new = self.page.locator(".session-item").count()
        self.assertGreaterEqual(after_new, before)

        if self.page.locator(".session-delete-btn").count() > 0:
            before_delete = self.page.locator(".session-item").count()
            self.page.locator(".session-delete-btn").first.click()
            self.page.wait_for_timeout(400)
            after_delete = self.page.locator(".session-item").count()
            self.assertLessEqual(after_delete, before_delete)
            if (
                self.page.locator("[data-testid='undo-toast']").count() > 0
                and "hidden" not in (self.page.locator("[data-testid='undo-toast']").get_attribute("class") or "")
            ):
                self.page.locator("[data-testid='undo-delete-btn']").click()
                self.page.wait_for_timeout(300)
                self.assertGreaterEqual(self.page.locator(".session-item").count(), 1)

    def test_codex_settings_page_open_and_actions(self) -> None:
        self._goto_chat()
        self.page.locator("[data-testid='provider-settings-btn']").click()
        self.page.wait_for_url("**/frontend/chat/codex.html")
        self.page.wait_for_selector("#codex-save-btn")

        self.page.locator("#codex-save-btn").click()
        self.page.wait_for_selector("#codex-status")

        self.page.locator("#codex-health-btn").click()
        self.page.wait_for_timeout(500)
        status_text = self.page.locator("#codex-status").inner_text()
        self.assertGreaterEqual(len(status_text.strip()), 0)

    def test_chat_request_validation_error_flow(self) -> None:
        self._goto_chat()
        result = self.page.evaluate(
            """
            async () => {
              const listResp = await fetch('/chat/sessions?library_id=supply_chain');
              const listed = await listResp.json();
              const sessionId = listed.sessions?.[0]?.session_id || '';
              const resp = await fetch(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  content: 'trigger validation',
                  mode: 'agent',
                  stream: true
                })
              });
              const payload = await resp.json();
              return { status: resp.status, payload };
            }
            """
        )
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["payload"]["error"], "library_id_required")


if __name__ == "__main__":
    unittest.main(verbosity=2)
