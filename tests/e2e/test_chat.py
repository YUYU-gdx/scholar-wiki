from __future__ import annotations

"""
E2E tests for the Chat panel of KN Graph Workbench.

These tests load the built frontend from disk (file:// protocol) and interact
with the already-running backend at http://127.0.0.1:8013.

Because the frontend uses module scripts with relative paths, Chromium must be
launched with --disable-web-security to bypass CORS restrictions imposed by the
file:// origin.

Run:
    uv run python tests/e2e/test_chat.py
"""

import unittest
from playwright.sync_api import sync_playwright, Page, Browser

BACKEND_URL = "http://127.0.0.1:8013"
FRONTEND_URL = "file:///D:/Code/kn_gragh/scholarai-workbench/dist/index.html"


class ChatE2ETest(unittest.TestCase):
    """E2E tests for the Chat panel."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser: Browser = cls._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-web-security",
                "--allow-file-access-from-files",
            ],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_browser") and cls._browser:
            cls._browser.close()
        if hasattr(cls, "_pw") and cls._pw:
            cls._pw.stop()

    def setUp(self) -> None:
        self.page: Page = self._browser.new_page()

        # The frontend api.ts module defaults API_BASE to '' unless
        # window.desktopShell.getBackendUrlSync exists.  Inject it before
        # any app scripts run so all fetch calls hit the live backend.
        self.page.add_init_script(
            "window.desktopShell = {"
            "  getBackendUrlSync: function() { return '" + BACKEND_URL + "'; }"
            "};"
        )

        # Collect console messages and page errors for debugging failures
        self._console: list[str] = []
        self.page.on("console", lambda msg: self._console.append(f"[{msg.type}] {msg.text}"))
        self.page.on("pageerror", lambda err: self._console.append(f"[PAGE_ERROR] {err}"))

    def tearDown(self) -> None:
        self.page.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _navigate_to(self, label: str) -> None:
        """Click a sidebar navigation button by its visible label text.

        The nav buttons live inside a <nav> element, which disambiguates
        them from other UI elements that might share the same text.
        """
        self.page.click(f"nav button:has-text('{label}')")
        self.page.wait_for_timeout(800)

    def _dump_console(self) -> str:
        return "\n".join(self._console[-30:]) or "(no console output)"

    def _page_errors(self) -> list[str]:
        """Return console lines that indicate errors."""
        return [
            line
            for line in self._console
            if line.startswith("[error]") or line.startswith("[PAGE_ERROR]")
        ]

    # ------------------------------------------------------------------
    # Test 1: Chat loads
    # ------------------------------------------------------------------

    def test_01_chat_loads(self) -> None:
        """Switch to Chat tab -- the panel renders without crashing."""
        self.page.goto(FRONTEND_URL)
        self.page.wait_for_timeout(3000)

        # Navigate to Chat
        self._navigate_to("Chat")

        # The Chat panel sidebar header should be visible
        self.assertTrue(
            self.page.locator("text=Sessions").is_visible(),
            f"Chat panel did not load; Sessions header missing.\nErrors:\n{self._page_errors()}",
        )

    # ------------------------------------------------------------------
    # Test 2: Session list
    # ------------------------------------------------------------------

    def test_02_session_list(self) -> None:
        """Chat sidebar shows chat sessions or an empty-state CTA."""
        self.page.goto(FRONTEND_URL)
        self.page.wait_for_timeout(3000)

        self._navigate_to("Chat")

        # The "Sessions" heading must be present
        self.assertTrue(
            self.page.locator("text=Sessions").is_visible(),
            f"Chat panel sidebar is missing.\nErrors:\n{self._page_errors()}",
        )

        # Either existing session cards are shown, or the empty-state
        # contains a "New Session" button.  Both are acceptable.
        new_session_visible = self.page.locator('button:has-text("New Session")').is_visible()
        # Session cards are rendered as divs in the session sidebar; check
        # by looking for elements that contain the Clock icon (Lucide).
        clock_icons = self.page.locator("aside div svg.lucide-clock")
        has_sessions = clock_icons.count() > 0

        has_content = new_session_visible or has_sessions
        self.assertTrue(
            has_content,
            f"Expected session entries or 'New Session' button.\nErrors:\n{self._page_errors()}",
        )

    # ------------------------------------------------------------------
    # Test 3: Create session
    # ------------------------------------------------------------------

    def test_03_create_session(self) -> None:
        """Click the new-chat button and verify a session appears."""
        self.page.goto(FRONTEND_URL)
        self.page.wait_for_timeout(3000)

        self._navigate_to("Chat")

        # Count existing session cards by counting Clock icons
        before_count = self.page.locator("aside div svg.lucide-clock").count()

        # Click the PlusSquare button in the Sessions header
        # (the button right after the <h2>Sessions</h2> heading)
        plus_btn = self.page.locator("aside h2 + button")
        if plus_btn.is_visible():
            plus_btn.click()
        else:
            # Fallback: click the "New Session" button in the empty state
            self.page.click('button:has-text("New Session")')

        self.page.wait_for_timeout(2000)

        after_count = self.page.locator("aside div svg.lucide-clock").count()

        self.assertGreater(
            after_count,
            before_count,
            f"Expected new session to appear. Before: {before_count}, After: {after_count}\nErrors:\n{self._page_errors()}",
        )

    # ------------------------------------------------------------------
    # Test 4: Session title
    # ------------------------------------------------------------------

    def test_04_session_title(self) -> None:
        """A newly created session must have a non-empty title."""
        self.page.goto(FRONTEND_URL)
        self.page.wait_for_timeout(3000)

        self._navigate_to("Chat")

        # Create a session
        plus_btn = self.page.locator("aside h2 + button")
        if plus_btn.is_visible():
            plus_btn.click()
        else:
            self.page.click('button:has-text("New Session")')

        self.page.wait_for_timeout(2000)

        # The ChatView prepends new sessions to the top of the list.
        # Session cards render the title inside a <p> element with classes
        # "text-sm font-medium truncate flex-1".
        title_elements = self.page.locator("aside div p.text-sm.font-medium")
        titles = title_elements.all_text_contents()

        self.assertTrue(
            len(titles) > 0,
            f"No session titles found.\nErrors:\n{self._page_errors()}",
        )

        # At minimum, the first title should not be empty.
        first_title = titles[0].strip()
        self.assertTrue(
            len(first_title) > 0,
            f"First session title is empty.\nErrors:\n{self._page_errors()}",
        )

    # ------------------------------------------------------------------
    # Test 5: Navigate away and back
    # ------------------------------------------------------------------

    def test_05_navigate_and_return(self) -> None:
        """Switch to Library then back to Chat -- sessions persist."""
        self.page.goto(FRONTEND_URL)
        self.page.wait_for_timeout(3000)

        self._navigate_to("Chat")
        self.page.wait_for_timeout(1000)

        before_count = self.page.locator("aside div svg.lucide-clock").count()

        # Navigate to Library
        self._navigate_to("Library")
        self.page.wait_for_timeout(1000)

        # Navigate back to Chat
        self._navigate_to("Chat")
        self.page.wait_for_timeout(1000)

        after_count = self.page.locator("aside div svg.lucide-clock").count()

        self.assertEqual(
            before_count,
            after_count,
            f"Sessions changed after navigate-away: {before_count} -> {after_count}\nErrors:\n{self._page_errors()}",
        )

    # ------------------------------------------------------------------
    # Test 6: Send message without crashing
    # ------------------------------------------------------------------

    def test_06_send_message_no_crash(self) -> None:
        """Type a message and click Send -- the UI must not crash."""
        self.page.goto(FRONTEND_URL)
        self.page.wait_for_timeout(3000)

        self._navigate_to("Chat")

        # Make sure we have an active session so the textarea is visible.
        existing_sessions = self.page.locator("aside div svg.lucide-clock")
        if existing_sessions.count() > 0:
            # Click the first session card to make it active
            self.page.locator("aside div[class*='cursor-pointer']").first.click()
            self.page.wait_for_timeout(1500)
        else:
            # Create a new session first
            plus_btn = self.page.locator("aside h2 + button")
            if plus_btn.is_visible():
                plus_btn.click()
            else:
                self.page.click('button:has-text("New Session")')
            self.page.wait_for_timeout(2000)

        # The textarea should now be visible (activeSessionId is set)
        textarea = self.page.locator("textarea[placeholder='Ask about your research...']")
        if not textarea.is_visible():
            self.skipTest(
                f"Chat input textarea not visible (no active session or API error).\nErrors:\n{self._page_errors()}"
            )

        # Type and send a message
        textarea.fill("Hello, this is an automated E2E test message.")

        send_btn = self.page.locator('button:has-text("Send")')
        self.assertTrue(
            send_btn.is_visible(),
            f"Send button not visible.\nErrors:\n{self._page_errors()}",
        )
        send_btn.click()

        # Wait briefly for the async send to settle.  We deliberately do
        # NOT wait for the AI response; we only verify the UI did not crash.
        self.page.wait_for_timeout(3000)

        # The Chat panel should still be present
        self.assertTrue(
            self.page.locator("text=Sessions").is_visible(),
            f"Page appears to have crashed after sending message.\nErrors:\n{self._page_errors()}",
        )

        # A user message bubble should now contain the text we typed
        user_msg = self.page.locator('p:has-text("Hello, this is an automated E2E test message.")')
        self.assertTrue(
            user_msg.is_visible(),
            f"User message bubble did not appear after send.\nErrors:\n{self._page_errors()}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
