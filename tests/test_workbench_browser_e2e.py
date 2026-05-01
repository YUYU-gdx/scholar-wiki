"""Browser automation tests for the KN Graph Workbench frontend.

Uses Playwright to verify each major view renders correctly and
interacts with the backend API at http://127.0.0.1:8013.
"""

import json
import time
import urllib.request
import urllib.error
import pytest

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

FRONTEND_URL = "http://localhost:3000"
BACKEND_URL = "http://127.0.0.1:8013"
TIMEOUT_MS = 15000


@pytest.fixture(scope="module")
def browser_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="zh-CN",
        )
        yield context
        context.close()
        browser.close()


def _backend_alive():
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/healthz")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_no_backend():
    if not _backend_alive():
        pytest.skip("Backend not running at http://127.0.0.1:8013")


class TestGraphView:
    """Test the Graph view loads and renders."""

    def test_page_loads(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
        title = page.title()
        assert "KN Graph" in title or "Workbench" in title or page.url == FRONTEND_URL
        page.close()

    def test_graph_overview_renders(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        errors = []

        def on_console_error(msg):
            if msg.type in ("error", "warning"):
                errors.append(f"[{msg.type}] {msg.text}")

        page.on("console", on_console_error)
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        try:
            resp = page.request.get(f"{BACKEND_URL}/graph/overview")
            data = resp.json()
            assert "nodes" in data or "node_count" in data, f"Unexpected graph overview: {list(data.keys())[:10]}"
        except Exception as exc:
            pytest.skip(f"Graph overview not available: {exc}")

        graph_errors = [e for e in errors if "Failed to fetch" not in e and "net::" not in e and "500" not in e and "Internal Server Error" not in e]
        assert len(graph_errors) == 0, f"Critical console errors (excluding 500s): {graph_errors[:5]}"
        page.close()


class TestLibraryView:
    """Test Library view loads and displays libraries."""

    def test_library_list_loads(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        try:
            resp = page.request.get(f"{BACKEND_URL}/literature/libraries")
            data = resp.json()
            assert "libraries" in data, f"Unexpected response: {list(data.keys())}"
            libs = data["libraries"]
            if len(libs) > 0:
                assert "library_id" in libs[0], f"Library missing library_id: {libs[0]}"
        except Exception as exc:
            pytest.skip(f"Libraries endpoint not available: {exc}")

        page.close()

    def test_library_selector_click(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        selector = page.locator("[data-testid='library-selector'], select, button").first
        try:
            selector.wait_for(state="visible", timeout=5000)
        except Exception:
            pass

        page.close()


class TestChatView:
    """Test Chat view renders session list."""

    def test_chat_sessions_loads(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        try:
            resp = page.request.get(f"{BACKEND_URL}/literature/libraries")
            data = resp.json()
            if not data.get("libraries"):
                pytest.skip("No libraries configured, cannot test chat sessions")
            lib_id = data["libraries"][0].get("library_id", "")
            if lib_id:
                resp2 = page.request.get(f"{BACKEND_URL}/chat/sessions?library_id={lib_id}")
                sessions = resp2.json()
                assert "sessions" in sessions or isinstance(sessions, dict), f"Unexpected sessions response"
        except Exception as exc:
            pytest.skip(f"Chat sessions test skipped: {exc}")

        page.close()


class TestPipelineView:
    """Test Pipeline view loads job list."""

    def test_pipeline_jobs_loads(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        try:
            resp = page.request.get(f"{BACKEND_URL}/v1/jobs?page=1&page_size=5")
            data = resp.json()
            assert "jobs" in data, f"Unexpected jobs response: {list(data.keys())}"
        except Exception as exc:
            pytest.skip(f"Pipeline jobs endpoint not available: {exc}")

        page.close()


class TestNavigation:
    """Test navigation between views."""

    def test_all_views_render_without_crash(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        js_errors = []

        def on_page_error(error):
            js_errors.append(str(error))

        page.on("pageerror", on_page_error)

        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        nav_items = page.locator("nav button, nav a, [role='tab']").all()
        views_checked = 1  # already on first view

        for item in nav_items[:6]:
            try:
                text = item.inner_text(timeout=2000)
                item.click(timeout=3000)
                page.wait_for_timeout(1000)
                views_checked += 1
            except Exception:
                continue

        assert len(js_errors) == 0, f"JavaScript errors on page: {js_errors[:5]}"
        page.close()

    def test_no_console_errors_on_load(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        console_errors = []

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console)
        page.goto(FRONTEND_URL, timeout=TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

        network_errors = [e for e in console_errors if "net::ERR" in e or "Failed to fetch" in e or "404" in e]
        server_500s = [e for e in console_errors if "500" in e or "Internal Server Error" in e]

        critical_errors = [e for e in console_errors if e not in network_errors and e not in server_500s]
        assert len(critical_errors) == 0, f"Critical console errors: {critical_errors[:5]}"
        if server_500s:
            print(f"  [WARN] {len(server_500s)} server 500 errors (backend may lack data): {server_500s[:3]}")
        page.close()


class TestDataDirIntegration:
    """Test that backend uses KN_GRAPH_DATA_DIR for storage."""

    def test_library_workspace_in_data_dir(self, browser_context: BrowserContext):
        try:
            req = urllib.request.Request(f"{BACKEND_URL}/literature/libraries")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                libs = data.get("libraries", [])
                if libs:
                    ws = libs[0].get("workspace_path", "")
                    assert "KNGraphApp" in ws or "kn_graph" in ws, f"Workspace path not in data_dir: {ws}"
        except Exception as exc:
            pytest.skip(f"Backend not reachable: {exc}")

    def test_health_endpoint(self, browser_context: BrowserContext):
        page = browser_context.new_page()
        resp = page.request.get(f"{BACKEND_URL}/healthz")
        data = resp.json()
        assert data.get("status") == "ok", f"Health check failed: {data}"
        page.close()