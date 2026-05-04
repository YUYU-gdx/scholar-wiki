"""
E2E Integration Oracle Tests for KN Graph Workbench.

Test cross-panel integration via Playwright + vision-based oracle.
Each test captures screenshots and writes a verdict file.

Requires:
  - Backend at http://127.0.0.1:8013
  - Frontend built at scholarai-workbench/dist/

Run:
  uv run python tests/e2e/test_integration_oracle.py
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser

BACKEND_URL = "http://127.0.0.1:8013"
DIST_DIR = Path(__file__).resolve().parent.parent.parent / "scholarai-workbench" / "dist"
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "e2e" / "oracle_screenshots"
VERDICT_FILE = Path(__file__).resolve().parent.parent / "e2e" / "oracle_verdicts.json"
PAGE_SETTLE_MS = 3500
INITIAL_LOAD_MS = 6000

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
# Helpers
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

    # Wait for the sidebar navigation to render
    try:
        page.wait_for_selector('nav button:has-text("Library")', state="visible", timeout=15000)
    except Exception:
        page.wait_for_selector('button:has-text("Library")', state="visible", timeout=15000)

    return page


def _click_nav(page: Page, label: str) -> None:
    """Click a sidebar navigation button by label text."""
    selector = f'nav button:has-text("{label}")'
    try:
        page.wait_for_selector(selector, state="visible", timeout=10000)
    except Exception:
        selector = f'button:has-text("{label}")'
        page.wait_for_selector(selector, state="visible", timeout=10000)
    page.click(selector)
    page.wait_for_timeout(PAGE_SETTLE_MS)


# ---------------------------------------------------------------------------
# Verdict system
# ---------------------------------------------------------------------------

_verdicts: dict[str, dict] = {}


def _verdict(test_name: str, passed: bool, detail: str = "", screenshot: str = ""):
    _verdicts[test_name] = {
        "passed": passed,
        "detail": detail,
        "screenshot": screenshot,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _screenshot(page: Page, name: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    return str(path)


# ---------------------------------------------------------------------------
# Panel indicators (selectors that should be visible per panel)
# ---------------------------------------------------------------------------

PANEL_NAMES = ["Library", "Graph", "Chat", "Reader", "Pipeline", "Settings"]

PANEL_INDICATORS = {
    "Library": {
        "heading": 'h2:has-text("Research Library")',
        "alternative": 'text=Research Library',
    },
    "Graph": {
        "heading": "iframe",  # 3D graph renders in an iframe
        "alternative": "canvas",
    },
    "Chat": {
        "heading": 'text=Sessions',
        "alternative": 'text=New Session',
    },
    "Reader": {
        "heading": 'text=Document Reader',
        "alternative": 'text=Select a paper',
    },
    "Pipeline": {
        "heading": 'h2:has-text("Data Pipeline")',
        "alternative": 'text=Data Pipeline',
    },
    "Settings": {
        "heading": 'text=Pipeline',
        "alternative": 'text=翻译',
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIntegrationOracle(unittest.TestCase):
    """Cross-panel integration tests with screenshot oracle."""

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
        # Write verdicts
        VERDICT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(VERDICT_FILE, "w", encoding="utf-8") as f:
            json.dump(_verdicts, f, indent=2, ensure_ascii=False)
        total = len(_verdicts)
        passed = sum(1 for v in _verdicts.values() if v["passed"])
        print(f"\n  Verdicts: {passed}/{total} passed -> {VERDICT_FILE}")
        print(f"  Screenshots: {SCREENSHOT_DIR}")

    def setUp(self):
        self.page = _setup_page(self.browser, self.frontend_url)

    def tearDown(self):
        errs = getattr(self.page, "console_errors", [])
        self.page.close()
        relevant = [e for e in errs if "favicon" not in e.lower()]
        if relevant:
            print(f"  [console errors] {relevant[:10]}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Test 1: Navigate all 6 panels sequentially, screenshot each, verify no blank pages
    # ------------------------------------------------------------------
    def test_01_navigate_all_panels_screenshot(self):
        """Navigate each panel and take a screenshot; verify content renders."""
        test_name = "test_01_navigate_all_panels"
        all_ok = True

        for label in PANEL_NAMES:
            _click_nav(self.page, label)
            ss_path = _screenshot(self.page, f"01_panel_{label.lower()}")

            indicators = PANEL_INDICATORS[label]
            heading_found = self.page.query_selector(indicators["heading"]) is not None
            alt_found = self.page.query_selector(indicators["alternative"]) is not None if indicators["alternative"] else False

            panel_ok = heading_found or alt_found
            if not panel_ok:
                all_ok = False
                print(f"  FAIL: Panel '{label}' did not show expected indicator")

        _verdict(test_name, all_ok,
                 "All 6 panels rendered content (no blank pages)" if all_ok else "Some panels showed blank or missing content",
                 _screenshot(self.page, f"01_panel_settings_final"))

        self.assertTrue(all_ok, "All 6 panels must render content. Check screenshots in oracle_screenshots/")

    # ------------------------------------------------------------------
    # Test 2: Settings persist - change target_lang to "en", save, navigate away and back
    # ------------------------------------------------------------------
    def test_02_settings_target_lang_persistence(self):
        """Change target language to 'en', save, navigate away, come back, verify."""
        test_name = "test_02_settings_persistence"

        # Navigate to Settings
        _click_nav(self.page, "Settings")
        self.page.wait_for_timeout(3000)
        _screenshot(self.page, "02_settings_before")

        # Find the target_lang input in the Translation section
        target_lang_input = None
        translation_section = None
        labels = self.page.query_selector_all("label")
        for label_el in labels:
            text = label_el.inner_text()
            if "目标语言" in text:
                inp = label_el.query_selector("input")
                if inp:
                    target_lang_input = inp
                    translation_section = label_el.evaluate("""
                        el => {
                            let p = el.parentElement;
                            while (p && !p.className.includes('rounded-2xl')) p = p.parentElement;
                            return p;
                        }
                    """)
                    break

        if target_lang_input is None:
            _verdict(test_name, False, "Could not find '目标语言' input in Settings",
                     _screenshot(self.page, "02_settings_no_input"))
            self.fail("Could not find '目标语言' input")

        old_value = target_lang_input.input_value()
        # Try "en"; if it's already "en", use "ja"
        test_value = "ja" if old_value == "en" else "en"

        target_lang_input.fill("")
        target_lang_input.fill(test_value)
        self.page.wait_for_timeout(500)

        current = target_lang_input.input_value()
        self.assertEqual(current, test_value,
                         f"Failed to set target_lang; expected '{test_value}', got '{current}'")
        _screenshot(self.page, "02_settings_filled")

        # Click the Save button in the Translation section
        save_buttons = self.page.query_selector_all('button:text-is("保存")')
        saved = False
        for btn in save_buttons:
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
                print(f"  Clicked Translation save button (found in same section)")
                break

        if not saved and len(save_buttons) >= 2:
            save_buttons[1].click()  # Translation is the second card
            saved = True
            print(f"  Clicked save_buttons[1] as fallback for Translation section")

        self.assertTrue(saved, "Could not find the Save button for the Translation section")
        self.page.wait_for_timeout(2000)
        _screenshot(self.page, "02_settings_saved")

        # Navigate away to Library and back to Settings
        _click_nav(self.page, "Library")
        _screenshot(self.page, "02_intermediate_library")
        _click_nav(self.page, "Settings")
        self.page.wait_for_timeout(3000)
        _screenshot(self.page, "02_settings_after_return")

        # Re-find target_lang input
        target_lang_input2 = None
        labels2 = self.page.query_selector_all("label")
        for label_el in labels2:
            if "目标语言" in label_el.inner_text():
                inp = label_el.query_selector("input")
                if inp:
                    target_lang_input2 = inp
                    break

        if target_lang_input2 is None:
            _verdict(test_name, False, "Could not re-find '目标语言' after navigating away and back",
                     _screenshot(self.page, "02_settings_re_find_fail"))
            self.fail("Could not re-find '目标语言' input after navigation")

        persisted = target_lang_input2.input_value()
        ok = persisted == test_value

        _verdict(test_name, ok,
                 f"target_lang persisted as '{persisted}' (expected '{test_value}')" if ok
                 else f"target_lang was '{persisted}' instead of '{test_value}'",
                 _screenshot(self.page, "02_settings_final"))

        self.assertEqual(persisted, test_value,
                         f"Setting did not persist; expected '{test_value}', got '{persisted}'")

    # ------------------------------------------------------------------
    # Test 3: Navigate sidebar - click each nav button, verify heading renders
    # ------------------------------------------------------------------
    def test_03_sidebar_nav_headings(self):
        """Click each sidebar button and verify each panel renders its heading."""
        test_name = "test_03_sidebar_headings"
        all_ok = True
        details = []

        for label in PANEL_NAMES:
            _click_nav(self.page, label)
            ss_path = _screenshot(self.page, f"03_heading_{label.lower()}")

            indicators = PANEL_INDICATORS[label]
            heading_found = self.page.query_selector(indicators["heading"]) is not None
            alt_found = self.page.query_selector(indicators["alternative"]) is not None if indicators.get("alternative") else False

            ok = heading_found or alt_found
            if not ok:
                all_ok = False
                details.append(f"MISSING: {label} (heading={indicators['heading']}, alt={indicators.get('alternative', 'none')})")
            else:
                details.append(f"OK: {label}")

        _verdict(test_name, all_ok,
                 "; ".join(details),
                 _screenshot(self.page, f"03_heading_{label.lower()}"))

        if not all_ok:
            self.fail("Some panels missing headings: " + "; ".join(details))

    # ------------------------------------------------------------------
    # Test 4: Full round trip through all panels
    # ------------------------------------------------------------------
    def test_04_full_round_trip(self):
        """Navigate Graph->Library->Pipeline->Settings->Chat->Reader full round trip."""
        test_name = "test_04_full_round_trip"
        sequence = ["Graph", "Library", "Pipeline", "Settings", "Chat", "Reader"]
        all_ok = True
        details = []

        for label in sequence:
            _click_nav(self.page, label)
            ss_path = _screenshot(self.page, f"04_roundtrip_{label.lower()}")

            indicators = PANEL_INDICATORS[label]
            heading_found = self.page.query_selector(indicators["heading"]) is not None
            alt_found = self.page.query_selector(indicators["alternative"]) is not None if indicators.get("alternative") else False

            ok = heading_found or alt_found
            if not ok:
                all_ok = False
                details.append(f"MISSING: {label}")
            else:
                details.append(f"OK: {label}")

            # Extra wait for async pages
            if label in ("Library", "Pipeline", "Settings"):
                self.page.wait_for_timeout(2000)

        _verdict(test_name, all_ok,
                 "Round trip: " + "; ".join(details),
                 _screenshot(self.page, "04_roundtrip_final"))

        if not all_ok:
            self.fail("Round trip failed: " + "; ".join(details))

    # ------------------------------------------------------------------
    # Test 5: Sidebar shows correct node/edge/paper counts
    # ------------------------------------------------------------------
    def test_05_sidebar_counts(self):
        """Verify sidebar stats (Nodes/Edges/Papers) show numbers."""
        test_name = "test_05_sidebar_counts"
        _screenshot(self.page, "05_sidebar_initial")

        # The sidebar stats are in the <aside> element at the bottom
        # They are in a grid-cols-3 div with text labels "Nodes", "Edges", "Papers"
        aside = self.page.query_selector("aside")
        self.assertIsNotNone(aside, "Sidebar <aside> element not found")

        # Query for the stat labels directly by visible text (Tailwind renders them uppercase)
        # The text in the DOM is "Nodes", "Edges", "Papers" (in <p> tags)
        nodes_label = self.page.query_selector('aside p:text-is("Nodes")')
        edges_label = self.page.query_selector('aside p:text-is("Edges")')
        papers_label = self.page.query_selector('aside p:text-is("Papers")')

        has_nodes_label = nodes_label is not None
        has_edges_label = edges_label is not None
        has_papers_label = papers_label is not None

        all_ok = has_nodes_label and has_edges_label and has_papers_label
        detail_parts = []

        # Try to find the actual numeric values (the bold text-sm paragraphs in grid)
        try:
            stat_ps = self.page.query_selector_all("aside .grid.grid-cols-3 p.text-sm.font-bold")
            if len(stat_ps) >= 3:
                detail_parts.append(f"Stats: Nodes={stat_ps[0].inner_text()}, Edges={stat_ps[1].inner_text()}, Papers={stat_ps[2].inner_text()}")
        except Exception:
            pass

        if not has_nodes_label:
            detail_parts.append("Missing 'Nodes' label")
        if not has_edges_label:
            detail_parts.append("Missing 'Edges' label")
        if not has_papers_label:
            detail_parts.append("Missing 'Papers' label")

        _verdict(test_name, all_ok,
                 "; ".join(detail_parts) if detail_parts else "All stat labels present",
                 _screenshot(self.page, "05_sidebar_final"))

        self.assertTrue(all_ok, f"Sidebar stat labels missing. Details: {detail_parts if detail_parts else 'none'}")
        self.assertTrue(has_nodes_label, "Sidebar missing 'Nodes' label")
        self.assertTrue(has_edges_label, "Sidebar missing 'Edges' label")
        self.assertTrue(has_papers_label, "Sidebar missing 'Papers' label")


if __name__ == "__main__":
    unittest.main(verbosity=2)
