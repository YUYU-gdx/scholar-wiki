"""
E2E integration tests for cross-panel functionality of the KN Graph Workbench.

Requires:
  - Backend at http://127.0.0.1:8013
  - Frontend built at scholarai-workbench/dist/

Run:
  uv run python tests/e2e/test_integration.py
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser

BACKEND_URL = "http://127.0.0.1:8013"
DIST_DIR = Path(__file__).resolve().parent.parent.parent / "scholarai-workbench" / "dist"
PAGE_SETTLE_MS = 3000
INITIAL_LOAD_MS = 5000

# ---------------------------------------------------------------------------
# Embedded HTTP server
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def log_message(self, format, *args):
        pass


def _start_http_server(port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), _QuietHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# Backend API helper
# ---------------------------------------------------------------------------

def _api_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make a JSON request to the backend API."""
    url = f"{BACKEND_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"API {method} {path} returned {e.code}: {body_text}")


# ---------------------------------------------------------------------------
# Page setup helpers
# ---------------------------------------------------------------------------

def _setup_page(browser: Browser, frontend_url: str) -> Page:
    """Create a page with backend URL injection and wait for the app to be ready."""
    page = browser.new_page()

    page.add_init_script(f"""
        window.desktopShell = {{
            getBackendUrlSync: function() {{ return '{BACKEND_URL}'; }}
        }};
    """)

    page.console_errors = []
    page.on("console", lambda msg: page.console_errors.append(msg.text) if msg.type == "error" else None)

    page.goto(frontend_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(INITIAL_LOAD_MS)

    # Wait for the sidebar navigation to render (library list loads async)
    try:
        page.wait_for_selector('nav button:has-text("Library")', state="visible", timeout=15000)
    except Exception:
        # Fallback: wait for any sidebar button
        page.wait_for_selector('button:has-text("Library")', state="visible", timeout=15000)

    return page


def _click_nav(page: Page, label: str) -> None:
    """Click a sidebar navigation button by label text."""
    # Scope to the sidebar nav element to avoid matching content text in panels
    selector = f'nav button:has-text("{label}")'
    try:
        page.wait_for_selector(selector, state="visible", timeout=10000)
    except Exception:
        # Fallback: try unscoped button selector
        selector = f'button:has-text("{label}")'
        page.wait_for_selector(selector, state="visible", timeout=10000)
    page.click(selector)
    page.wait_for_timeout(PAGE_SETTLE_MS)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PANEL_NAMES = ["Library", "Graph", "Chat", "Reader", "Pipeline", "Settings"]

PANEL_INDICATORS = {
    "Library": 'h2:text("Research Library")',
    "Graph": "iframe",
    "Chat": 'h2:text-is("Sessions")',
    "Reader": 'h3:text("Document Reader")',
    "Pipeline": 'h2:text("Data Pipeline")',
    "Settings": 'text=全局设置',
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCrossPanelIntegration(unittest.TestCase):
    """Tests that verify behavior across multiple panels."""

    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

        cls.http_port = _find_free_port()
        cls.http_server = _start_http_server(cls.http_port)
        cls.frontend_url = f"http://127.0.0.1:{cls.http_port}/index.html"
        print(f"\n  Frontend served at {cls.frontend_url}")

    @classmethod
    def tearDownClass(cls):
        cls.http_server.shutdown()
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = _setup_page(self.browser, self.frontend_url)

    def tearDown(self):
        errs = getattr(self.page, "console_errors", [])
        self.page.close()
        relevant = [e for e in errs if "favicon" not in e.lower()]
        if relevant:
            print(f"  [console errors] {relevant[:10]}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Test 1: Navigate all 6 panels without crashes
    # ------------------------------------------------------------------
    def test_navigate_all_six_panels(self):
        """Navigate through every panel in sequence; each renders correctly."""
        for label in PANEL_NAMES:
            _click_nav(self.page, label)

            indicator = PANEL_INDICATORS[label]
            el = self.page.query_selector(indicator)
            self.assertIsNotNone(
                el,
                f"Panel '{label}' did not render: selector '{indicator}' not found"
            )

            if label in ("Library", "Pipeline", "Settings"):
                self.page.wait_for_timeout(2000)

    # ------------------------------------------------------------------
    # Test 2: Rapid panel cycling (stress test)
    # ------------------------------------------------------------------
    def test_navigation_forward_back_cycle(self):
        """Rapidly cycle through panels to stress-test view switching."""
        for cycle_num in range(2):
            for label in PANEL_NAMES:
                _click_nav(self.page, label)
                # Settings loads async data, needs extra time
                if label in ("Library", "Pipeline", "Settings"):
                    self.page.wait_for_timeout(2000)
                indicator = PANEL_INDICATORS[label]
                el = self.page.query_selector(indicator)
                self.assertIsNotNone(el,
                    f"Panel '{label}' missing in cycle {cycle_num + 1} (selector: {indicator})")

    # ------------------------------------------------------------------
    # Test 3: Settings persist across navigation (with save)
    # ------------------------------------------------------------------
    def test_settings_persist_across_navigation(self):
        """Change a setting, save it, navigate away, come back - value persists."""
        _click_nav(self.page, "Settings")
        self.page.wait_for_timeout(3000)  # Settings loads via async API call

        # Find the target_lang input in the Translation settings section
        target_lang_input = None
        translation_section = None
        labels = self.page.query_selector_all("label")
        for label_el in labels:
            text = label_el.inner_text()
            if "目标语言" in text:
                inp = label_el.query_selector("input")
                if inp:
                    target_lang_input = inp
                    # Get the parent section div (the rounded-2xl container)
                    translation_section = label_el.evaluate("""
                        el => {
                            let p = el.parentElement;
                            while (p && !p.className.includes('rounded-2xl')) p = p.parentElement;
                            return p;
                        }
                    """)
                    break

        self.assertIsNotNone(target_lang_input,
                             "Could not find the '目标语言' (target language) input in Settings")

        old_value = target_lang_input.input_value()
        test_value = "fr" if old_value != "fr" else "ja"

        target_lang_input.fill("")  # clear
        target_lang_input.fill(test_value)
        self.page.wait_for_timeout(500)

        current = target_lang_input.input_value()
        self.assertEqual(current, test_value,
                         f"Failed to set target_lang; expected '{test_value}', got '{current}'")

        # Click the Save button in the Translation section
        # The section has a "保存" button at the top-right
        save_buttons = self.page.query_selector_all('button:text-is("保存")')
        saved = False
        for btn in save_buttons:
            # Check if this save button is in the same section as our input
            in_same_section = btn.evaluate("""
                (btn, section) => {
                    let p = btn.parentElement;
                    while (p) {
                        if (p === section) return true;
                        p = p.parentElement;
                    }
                    return false;
                }
            """, translation_section)
            if in_same_section:
                btn.click()
                saved = True
                break

        if not saved and save_buttons:
            # Fallback: click the second save button (Translation is middle section)
            # Pipeline = buttons[0], Translation = buttons[1], Agent = buttons[2]
            idx = 1 if len(save_buttons) >= 2 else 0
            save_buttons[idx].click()
            saved = True

        self.assertTrue(saved, "Could not find the Save button for the Translation section")
        self.page.wait_for_timeout(1500)  # wait for the save API call to complete

        # Navigate away and come back
        _click_nav(self.page, "Graph")
        _click_nav(self.page, "Settings")
        self.page.wait_for_timeout(3000)  # Settings reloads from backend

        # Re-find target_lang input
        target_lang_input2 = None
        labels2 = self.page.query_selector_all("label")
        for label_el in labels2:
            if "目标语言" in label_el.inner_text():
                inp = label_el.query_selector("input")
                if inp:
                    target_lang_input2 = inp
                    break

        self.assertIsNotNone(target_lang_input2,
                             "Could not re-find '目标语言' input after navigation")

        persisted = target_lang_input2.input_value()
        self.assertEqual(persisted, test_value,
                         f"Setting did not persist; expected '{test_value}', got '{persisted}'")

    # ------------------------------------------------------------------
    # Test 4: Library create and delete lifecycle
    # ------------------------------------------------------------------
    def test_library_create_and_delete(self):
        """Create a test library via sidebar UI, then delete it."""
        test_lib_id = f"e2e_del_test_{int(time.time()) % 100000}"

        # ---- Create library via sidebar ----
        # Click the "+" button to open the create-library input
        create_btn = self.page.query_selector('button[title="创建文献库"]')
        self.assertIsNotNone(create_btn, "Create library '+' button not found in sidebar")
        create_btn.click()
        self.page.wait_for_timeout(500)

        # Type the new library ID
        new_lib_input = self.page.query_selector('input[placeholder="library_id"]')
        self.assertIsNotNone(new_lib_input, "Library ID input not visible after clicking '+'")
        new_lib_input.fill(test_lib_id)

        # Click "创建" (Create) button
        create_confirm_btn = self.page.query_selector('button:text-is("创建")')
        self.assertIsNotNone(create_confirm_btn, "Create confirm button not found")
        create_confirm_btn.click()
        self.page.wait_for_timeout(2000)

        # Verify the library appears in the sidebar list
        lib_span = self.page.query_selector(f'span:text-is("{test_lib_id}")')
        self.assertIsNotNone(lib_span,
                             f"Library '{test_lib_id}' not visible in sidebar after creation")

        # ---- Delete library ----
        trash_btn = self.page.query_selector(f'button[title="删除库 {test_lib_id}"]')
        self.assertIsNotNone(trash_btn,
                             f"Delete button not found for library '{test_lib_id}'")

        self.page.once("dialog", lambda d: d.accept())
        trash_btn.click()
        self.page.wait_for_timeout(2000)

        # Verify library is gone from sidebar
        lib_gone = self.page.query_selector(f'span:text-is("{test_lib_id}")')
        self.assertIsNone(lib_gone,
                          f"Library '{test_lib_id}' still visible after deletion")

    # ------------------------------------------------------------------
    # Test 5: Pipeline panel loads correctly
    # ------------------------------------------------------------------
    def test_pipeline_panel_loads(self):
        """Navigate to Pipeline and verify all expected UI elements."""
        _click_nav(self.page, "Pipeline")

        heading = self.page.query_selector('h2:has-text("Data Pipeline")')
        self.assertIsNotNone(heading, "Pipeline heading not found")

        # Jobs table OR "No pipeline jobs" message
        table = self.page.query_selector("table")
        no_jobs = self.page.query_selector('text=No pipeline jobs found')
        self.assertTrue(table is not None or no_jobs is not None,
                        "Pipeline panel has neither job table nor empty message")

        # Upload area
        upload_label = self.page.query_selector('label[for="pdf-upload"]')
        self.assertIsNotNone(upload_label, "PDF upload area not found")

        # Stream log
        log_section = self.page.query_selector('text=Pipeline Stream')
        self.assertIsNotNone(log_section, "Pipeline Stream section not found")

    # ------------------------------------------------------------------
    # Test 6: Chat panel loads sessions sidebar
    # ------------------------------------------------------------------
    def test_chat_panel_loads(self):
        """Navigate to Chat and verify session sidebar and new-session prompt."""
        _click_nav(self.page, "Chat")

        sessions_heading = self.page.query_selector('text=Sessions')
        self.assertIsNotNone(sessions_heading, "Chat sessions heading not found")

        placeholder = self.page.query_selector('text=Select or create a session')
        new_session_btn = self.page.query_selector('text=New Session')
        self.assertTrue(placeholder is not None or new_session_btn is not None,
                        "Chat panel shows neither session prompt nor New Session button")

    # ------------------------------------------------------------------
    # Test 7: Reader panel shows empty state
    # ------------------------------------------------------------------
    def test_reader_panel_empty_state(self):
        """Navigate to Reader without paper selection; verify empty state."""
        _click_nav(self.page, "Reader")

        heading = self.page.query_selector('text=Document Reader')
        self.assertIsNotNone(heading, "Reader heading not found")

        hint = self.page.query_selector('text=Select a paper')
        self.assertIsNotNone(hint, "Reader hint text not found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
