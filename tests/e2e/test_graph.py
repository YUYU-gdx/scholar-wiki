"""
E2E tests for the Graph panel of the KN Graph Workbench.

Requires:
  - Backend at http://127.0.0.1:8013
  - Frontend built at scholarai-workbench/dist/

Run:
  uv run python tests/e2e/test_graph.py
"""
from __future__ import annotations

import os
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
PAGE_SETTLE_MS = 3000
INITIAL_LOAD_MS = 5000

# ---------------------------------------------------------------------------
# Embedded HTTP server to serve the built frontend
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # suppress HTTP request logging


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

    # Wait for sidebar navigation to render
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
# Tests
# ---------------------------------------------------------------------------

class TestGraphPanel(unittest.TestCase):
    """Tests targeting the Graph panel specifically."""

    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

        # Start HTTP server to serve the frontend (avoids file:// CORS issues)
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
        # Filter out expected noise
        relevant = [e for e in errs if "favicon" not in e.lower()]
        if relevant:
            print(f"  [console errors] {relevant[:10]}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Test 1: Graph loads without errors
    # ------------------------------------------------------------------
    def test_graph_loads(self):
        """Switch to Graph view; page should render without errors."""
        _click_nav(self.page, "Graph")

        # Check for iframe in Graph view
        iframe = self.page.query_selector("iframe")
        self.assertIsNotNone(iframe, "No iframe found in Graph view")

        src = iframe.get_attribute("src") or ""
        self.assertIn("graph_3d", src, f"Iframe src does not point to graph_3d: {src}")

    # ------------------------------------------------------------------
    # Test 2: Node / edge / paper counts visible in sidebar
    # ------------------------------------------------------------------
    def test_node_edge_counts_visible(self):
        """Sidebar statistics show node, edge, and paper counts."""
        # The stat boxes are rendered in the sidebar as 3 divs each with 2 <p> tags.
        # First <p> is the count, second <p> is the label ("Nodes", "Edges", "Papers").
        # Use a single evaluate call to extract all three counts at once.
        stats = self.page.evaluate("""
            () => {
                const result = { nodes: '', edges: '', papers: '' };
                const labels = document.querySelectorAll('p');
                for (const p of labels) {
                    const text = p.textContent.trim();
                    if (text === 'Nodes' || text === 'Edges' || text === 'Papers') {
                        const parent = p.parentElement;
                        if (parent) {
                            const ps = parent.querySelectorAll('p');
                            for (const cp of ps) {
                                const t = cp.textContent.trim();
                                if (/^\\d+$/.test(t)) {
                                    const key = text === 'Nodes' ? 'nodes'
                                        : text === 'Edges' ? 'edges' : 'papers';
                                    result[key] = t;
                                }
                            }
                        }
                    }
                }
                return result;
            }
        """)

        nodes_label = self.page.query_selector('p:text-is("Nodes")')
        edges_label = self.page.query_selector('p:text-is("Edges")')
        papers_label = self.page.query_selector('p:text-is("Papers")')

        self.assertIsNotNone(nodes_label, "Sidebar 'Nodes' label not found")
        self.assertIsNotNone(edges_label, "Sidebar 'Edges' label not found")
        self.assertIsNotNone(papers_label, "Sidebar 'Papers' label not found")

        node_count = stats.get("nodes", "")
        edge_count = stats.get("edges", "")
        paper_count = stats.get("papers", "")

        self.assertTrue(node_count.isdigit(),
                        f"Node count is not a number: '{node_count}'")
        self.assertTrue(edge_count.isdigit(),
                        f"Edge count is not a number: '{edge_count}'")
        self.assertTrue(paper_count.isdigit(),
                        f"Paper count is not a number: '{paper_count}'")

        print(f"  Stats: Nodes={node_count}, Edges={edge_count}, Papers={paper_count}")

    # ------------------------------------------------------------------
    # Test 3: Graph visualization iframe present and visible
    # ------------------------------------------------------------------
    def test_graph_visualization(self):
        """Graph view contains the 3D visualization iframe with correct src."""
        _click_nav(self.page, "Graph")

        iframe = self.page.query_selector("iframe")
        self.assertIsNotNone(iframe, "Graph view does not contain an iframe")

        src = iframe.get_attribute("src") or ""
        self.assertTrue(len(src) > 0, "Iframe src is empty")
        self.assertIn("frontend_legacy", src,
                      f"Expected iframe to load from frontend_legacy, got: {src}")

        is_visible = iframe.is_visible()
        self.assertTrue(is_visible, "Graph iframe is not visible")

    # ------------------------------------------------------------------
    # Test 4: Header search navigates to Graph view
    # ------------------------------------------------------------------
    def test_search_navigates_to_graph(self):
        """Typing in header search and pressing Enter opens the Graph view."""
        # Start from Library
        _click_nav(self.page, "Library")
        heading = self.page.query_selector('h2:text("Research Library")')
        self.assertIsNotNone(heading, "Library view did not load")

        # Type in the header search box
        search_input = self.page.query_selector('input[placeholder*="Search"]')
        self.assertIsNotNone(search_input, "Search input not found in header")

        search_input.fill("supply chain")
        search_input.press("Enter")
        self.page.wait_for_timeout(PAGE_SETTLE_MS)

        # After Enter, app switches to Graph view
        iframe = self.page.query_selector("iframe")
        self.assertIsNotNone(iframe, "Should have navigated to Graph view after search")

        src = iframe.get_attribute("src") or ""
        self.assertIn("graph_3d", src,
                      f"Expected graph iframe after search, got src: {src}")

    # ------------------------------------------------------------------
    # Test 5: Graph -> Library -> Graph round-trip navigation
    # ------------------------------------------------------------------
    def test_navigate_graph_library_roundtrip(self):
        """Navigate from Graph to Library and back; both panels render correctly."""
        _click_nav(self.page, "Graph")
        iframe1 = self.page.query_selector("iframe")
        self.assertIsNotNone(iframe1, "Graph iframe not present on first visit")

        _click_nav(self.page, "Library")
        library_heading = self.page.query_selector('h2:text("Research Library")')
        self.assertIsNotNone(library_heading, "Library view did not load after Graph")
        iframe_gone = self.page.query_selector("iframe")
        self.assertIsNone(iframe_gone, "Graph iframe still present after navigating to Library")

        _click_nav(self.page, "Graph")
        iframe2 = self.page.query_selector("iframe")
        self.assertIsNotNone(iframe2, "Graph iframe not present after returning from Library")
        src2 = iframe2.get_attribute("src") or ""
        self.assertIn("graph_3d", src2, f"Iframe src wrong after round-trip: {src2}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
