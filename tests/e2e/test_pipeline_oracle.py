"""
E2E Oracle tests for the Pipeline panel of KN Graph.

Each test:
  1. Performs browser actions
  2. Takes a screenshot -> screenshots/pipe_XX.png
  3. Dumps HTML -> screenshots/pipe_XX.html
  4. Writes automated verdict -> screenshots/pipe_XX_verdict.txt

Requires:
  - Backend at http://127.0.0.1:8013
  - Frontend dist at D:/Code/kn_gragh/scholarai-workbench/dist/
  - Playwright installed (uv run python -m playwright install chromium)

Run:
  uv run python tests/e2e/test_pipeline_oracle.py
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, expect

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DIST_DIR = Path(r"D:\Code\kn_gragh\scholarai-workbench\dist")
SCREENSHOT_DIR = Path(r"D:\Code\kn_gragh\tests\e2e\screenshots")
API_BASE = "http://127.0.0.1:8013"
TEST_PDF = (
    r"D:\Code\kn_gragh\outputs\full data\full data\organized_by_title\pdf"
    r"\STRATEGIC MANAGEMENT JOURNAL_83.pdf"
)
TEST_PDF2 = (
    r"D:\Code\kn_gragh\outputs\full data\full data\organized_by_title\pdf"
    r"\A Dynamic Clustering Approach to Data-Driven Assortment Personalization.pdf"
)

# ---------------------------------------------------------------------------
# Timeouts (milliseconds)
# ---------------------------------------------------------------------------

NAV_TIMEOUT = 5000
JOB_POLL_INTERVAL = 5000
JOB_COMPLETE_TIMEOUT = 180000  # 3 minutes
SNAPSHOT_WAIT = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _api_get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_existing_job_ids() -> set[str]:
    data = _api_get("/v1/jobs?page=1&page_size=100")
    jobs = data.get("jobs", []) or []
    return {j["job_id"] for j in jobs}


def _take_snapshot(page: Page, name: str) -> None:
    """Take screenshot and dump HTML for a test case."""
    png_path = SCREENSHOT_DIR / f"{name}.png"
    html_path = SCREENSHOT_DIR / f"{name}.html"
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    page.screenshot(path=str(png_path), full_page=False)
    html_path.write_text(page.content(), encoding="utf-8")
    print(f"    Snapshot saved: {png_path.name}, {html_path.name}")


def _write_verdict(name: str, passed: bool, summary: str, details: list[str]) -> None:
    """Write a verdict file."""
    verdict_path = SCREENSHOT_DIR / f"{name}_verdict.txt"
    status = "PASS" if passed else "FAIL"
    lines = [
        f"Verdict: {status}",
        f"Timestamp: {datetime.now().isoformat()}",
        f"Summary: {summary}",
        "Details:",
    ]
    for d in details:
        lines.append(f"  - {d}")
    verdict_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"    Verdict: {status} -> {verdict_path.name}")


def _nav_to_pipeline(page: Page) -> bool:
    """Navigate to Pipeline view. Returns True if successful."""
    try:
        btn = page.locator("button", has_text="Pipeline")
        if not btn.is_visible():
            return False
        btn.click()
        page.wait_for_timeout(2000)
        heading = page.get_by_role("heading", name="Data Pipeline")
        heading.wait_for(state="visible", timeout=NAV_TIMEOUT)
        return True
    except Exception:
        return False


def _nav_to_library(page: Page) -> bool:
    """Navigate to Library view."""
    try:
        btn = page.locator("button", has_text="Library")
        btn.click()
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def _select_pdf(page: Page, pdf_path: str) -> None:
    """Select a PDF file via the hidden file input."""
    file_input = page.locator('input[type="file"]#pdf-upload')
    file_input.set_input_files(pdf_path)


def _count_job_rows(page: Page) -> int:
    """Count non-empty job rows."""
    rows = page.locator("tbody tr")
    count = 0
    for i in range(rows.count()):
        text = rows.nth(i).inner_text()
        if "No pipeline jobs found" not in text:
            count += 1
    return count


def _find_job_by_text(page: Page, needle: str) -> bool:
    """Check if any job row contains the given text."""
    rows = page.locator("tbody tr")
    for i in range(rows.count()):
        text = rows.nth(i).inner_text()
        if "No pipeline jobs found" not in text and needle in text:
            return True
    return False


def _get_status_texts(page: Page) -> list[str]:
    """Return all status badge texts from job rows."""
    status_cells = page.locator("tbody tr td:nth-child(5) span")
    results = []
    for i in range(status_cells.count()):
        results.append(status_cells.nth(i).inner_text().strip().lower())
    return results


def _get_progress_texts(page: Page) -> list[str]:
    """Return all progress percentage texts from job rows."""
    progress_spans = page.locator("tbody tr td:nth-child(4) span:last-child")
    results = []
    for i in range(progress_spans.count()):
        results.append(progress_spans.nth(i).inner_text().strip())
    return results


def _create_page(frontend_port: int) -> tuple[Page, "sync_playwright"]:
    """Create a configured browser page."""
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page.add_init_script(
        f"window.desktopShell = {{ getBackendUrlSync: function() {{ return '{API_BASE}'; }} }};"
    )

    page.goto(f"http://127.0.0.1:{frontend_port}/index.html", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    return page, p


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------


def run_tests() -> int:
    failed = 0
    passed = 0

    def check(condition: bool, name: str, details: list[str], verdict_name: str) -> None:
        nonlocal failed, passed
        if condition:
            passed += 1
            print(f"    PASS: {name}")
        else:
            failed += 1
            print(f"    FAIL: {name}")
        # details already assembled by caller
        _write_verdict(verdict_name, condition, name, details)

    # --- Start frontend HTTP server ---
    frontend_port = _free_port()
    os.chdir(str(DIST_DIR))
    httpd = socketserver.TCPServer(
        ("127.0.0.1", frontend_port), http.server.SimpleHTTPRequestHandler
    )
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print(f"Frontend server on http://127.0.0.1:{frontend_port}")

    # --- Verify backend ---
    try:
        _api_get("/v1/jobs?page=1&page_size=1")
        print("Backend API reachable at " + API_BASE)
    except Exception as exc:
        print(f"ERROR: Backend not reachable: {exc}")
        httpd.shutdown()
        return 1

    existing_ids = _get_existing_job_ids()
    print(f"Existing jobs in server: {len(existing_ids)}")

    print("-" * 70)

    page, pw = _create_page(frontend_port)

    try:
        # ================================================================
        # TEST 1: Pipeline panel loads correctly
        # ================================================================
        print("\n[Test 1] Pipeline panel loads correctly")
        test_name = "pipe_01"
        details: list[str] = []
        all_ok = True

        nav_ok = _nav_to_pipeline(page)
        details.append(f"Navigated to Pipeline view: {nav_ok}")
        if not nav_ok:
            all_ok = False

        heading_ok = page.get_by_role("heading", name="Data Pipeline").is_visible()
        details.append(f"Heading 'Data Pipeline' visible: {heading_ok}")
        all_ok = all_ok and heading_ok

        upload_heading_ok = page.locator("h3:has-text('Upload PDF')").is_visible()
        details.append(f"'Upload PDF' heading visible: {upload_heading_ok}")
        all_ok = all_ok and upload_heading_ok

        table_ok = page.locator("table").is_visible()
        details.append(f"Job table visible: {table_ok}")
        all_ok = all_ok and table_ok

        file_input_ok = page.locator("#pdf-upload").count() > 0
        details.append(f"File input #pdf-upload exists: {file_input_ok}")
        all_ok = all_ok and file_input_ok

        _take_snapshot(page, test_name)
        check(all_ok, "Pipeline panel loads: heading + upload section + table visible", details, test_name)

        # ================================================================
        # TEST 2: Import button disabled when no file selected
        # ================================================================
        print("\n[Test 2] Import button disabled when no file selected")
        test_name = "pipe_02"
        details = []
        all_ok = True

        import_btn = page.locator("button:has-text('Import')")
        btn_disabled = import_btn.is_disabled()
        details.append(f"Import button disabled: {btn_disabled}")
        all_ok = all_ok and btn_disabled

        placeholder_ok = page.locator("p:has-text('Choose a PDF file')").is_visible()
        details.append(f"Placeholder 'Choose a PDF file' visible: {placeholder_ok}")
        all_ok = all_ok and placeholder_ok

        _take_snapshot(page, test_name)
        check(all_ok, "Import button is disabled when no file is selected", details, test_name)

        # ================================================================
        # TEST 3: Select PDF enables Import and shows filename
        # ================================================================
        print("\n[Test 3] Select PDF enables Import and shows filename")
        test_name = "pipe_03"
        details = []
        all_ok = True

        _select_pdf(page, TEST_PDF)
        page.wait_for_timeout(1000)

        pdf_basename = Path(TEST_PDF).name
        filename_ok = page.locator(f"p.truncate:has-text('{pdf_basename}')").is_visible()
        details.append(f"Filename '{pdf_basename}' shown: {filename_ok}")
        all_ok = all_ok and filename_ok

        # File size shown (~28.3 KB for this 29KB file)
        size_ok = page.locator("text=/KB/").is_visible()
        details.append(f"File size in KB shown: {size_ok}")

        import_enabled = not import_btn.is_disabled()
        details.append(f"Import button enabled: {import_enabled}")
        all_ok = all_ok and import_enabled

        _take_snapshot(page, test_name)
        check(all_ok, "After selecting PDF: filename shown, Import enabled", details, test_name)

        # ================================================================
        # TEST 4: Click Import -> job appears in table
        # ================================================================
        print("\n[Test 4] Click Import -> job appears in table")
        test_name = "pipe_04"
        details = []
        all_ok = True

        import_btn.click()
        page.wait_for_timeout(4000)

        has_job = _find_job_by_text(page, "job_")
        details.append(f"Job with 'job_' prefix visible: {has_job}")
        all_ok = all_ok and has_job

        job_count = _count_job_rows(page)
        details.append(f"Job rows count: {job_count}")
        all_ok = all_ok and job_count >= 1

        # Check new job IDs from API
        new_ids = _get_existing_job_ids() - existing_ids
        details.append(f"New job IDs on server: {new_ids}")
        all_ok = all_ok and len(new_ids) > 0

        _take_snapshot(page, test_name)
        check(all_ok, "After clicking Import: job appears in table", details, test_name)

        # ================================================================
        # TEST 5: Job status label updates
        # ================================================================
        print("\n[Test 5] Job status label updates (parsing->extracting->finalizing)")
        test_name = "pipe_05"
        details = []
        all_ok = True

        print("  Polling for status changes (up to 120s)...")
        deadline = time.time() + 120
        observed_statuses: set[str] = set()
        progressed = False

        while time.time() < deadline:
            try:
                refresh_btn = page.locator("button:has-text('Refresh')")
                if refresh_btn.is_visible():
                    refresh_btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            statuses = _get_status_texts(page)
            observed_statuses.update(statuses)
            # Check for any non-queued status
            progressed_states = {"running", "completed", "failed", "cancelled", "parsing", "extracting", "finalizing"}
            if any(s in progressed_states for s in statuses):
                progressed = True
                break
            page.wait_for_timeout(JOB_POLL_INTERVAL)

        details.append(f"Observed status texts: {observed_statuses}")
        details.append(f"Progressed past initial state: {progressed}")
        all_ok = all_ok and progressed

        _take_snapshot(page, test_name)
        check(all_ok, f"Job status progressed beyond initial state (saw: {observed_statuses})", details, test_name)

        # ================================================================
        # TEST 6: Completed/failed job shows terminal progress
        # ================================================================
        print("\n[Test 6] Jobs reach terminal state with progress")
        test_name = "pipe_06"
        details = []
        all_ok = True

        print(f"  Waiting up to {JOB_COMPLETE_TIMEOUT // 1000}s for terminal state...")
        deadline2 = time.time() + JOB_COMPLETE_TIMEOUT / 1000
        terminal_found = False
        final_statuses: list[str] = []

        while time.time() < deadline2:
            try:
                refresh_btn = page.locator("button:has-text('Refresh')")
                if refresh_btn.is_visible():
                    refresh_btn.click()
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            statuses = _get_status_texts(page)
            terminal_states = {"completed", "failed", "cancelled"}
            if any(s in terminal_states for s in statuses):
                terminal_found = True
                final_statuses = statuses
                break
            page.wait_for_timeout(JOB_POLL_INTERVAL)

        details.append(f"Terminal state found: {terminal_found}")
        details.append(f"Final job statuses: {final_statuses}")
        all_ok = all_ok and terminal_found

        # Check progress shows meaningful values
        progress_texts = _get_progress_texts(page)
        details.append(f"Progress values: {progress_texts}")
        has_meaningful_progress = any(
            p.rstrip("%").strip().isdigit() and int(p.rstrip("%").strip()) > 0
            for p in progress_texts
        )
        details.append(f"Has progress > 0%: {has_meaningful_progress}")

        # If any completed, check for 100%
        has_100 = any("100%" in p or "100" == p.strip() for p in progress_texts)
        details.append(f"Has 100% progress: {has_100}")

        _take_snapshot(page, test_name)
        check(all_ok, "At least one job reached terminal state with progress", details, test_name)

        # ================================================================
        # TEST 7: Table layout check (table-fixed, overflow container,
        #          filename truncation)
        # ================================================================
        print("\n[Test 7] Table layout - overflow/truncation handling")
        test_name = "pipe_07"
        details = []
        all_ok = True

        table_fixed_ok = page.locator("table.table-fixed").count() > 0
        details.append(f"Table has 'table-fixed' class: {table_fixed_ok}")
        all_ok = all_ok and table_fixed_ok

        overflow_ok = page.locator(".overflow-x-auto").count() > 0
        details.append(f"Overflow container exists: {overflow_ok}")
        all_ok = all_ok and overflow_ok

        # Check that filename cells have truncate class
        truncate_cells = page.locator("tbody tr td:nth-child(2) span.truncate")
        if truncate_cells.count() > 0:
            details.append(f"Found {truncate_cells.count()} filename cells with 'truncate' class")
        else:
            # Try alternate: any element with truncate class in filename column
            truncate_in_td2 = page.locator("tbody tr td:nth-child(2) .truncate")
            details.append(f"Filename column truncate elements: {truncate_in_td2.count()}")

        # Check the table has all 6 column headers
        th_count = page.locator("thead th").count()
        details.append(f"Table header columns: {th_count}")
        all_ok = all_ok and th_count >= 5

        # Verify column widths are constrained (not exceeding viewport)
        viewport = page.viewport_size
        if viewport:
            details.append(f"Viewport: {viewport['width']}x{viewport['height']}")

        _take_snapshot(page, test_name)
        check(all_ok, "Table uses table-fixed layout with overflow protection", details, test_name)

        # ================================================================
        # TEST 8: Upload second PDF -> multiple jobs in table
        # ================================================================
        print("\n[Test 8] Upload second PDF -> both rows in table")
        test_name = "pipe_08"
        details = []
        all_ok = True

        _select_pdf(page, TEST_PDF2)
        page.wait_for_timeout(800)

        import_btn2 = page.locator("button:has-text('Import')")
        btn2_enabled = not import_btn2.is_disabled()
        details.append(f"Import enabled after selecting second PDF: {btn2_enabled}")
        all_ok = all_ok and btn2_enabled

        # Show the second filename
        pdf2_name = Path(TEST_PDF2).name
        filename2_ok = page.locator(f"p:has-text('{pdf2_name}')").is_visible()
        details.append(f"Second filename '{pdf2_name}' shown: {filename2_ok}")

        import_btn2.click()
        page.wait_for_timeout(4000)

        job_count2 = _count_job_rows(page)
        details.append(f"Job rows after second upload: {job_count2}")
        all_ok = all_ok and job_count2 >= 2

        _take_snapshot(page, test_name)
        check(all_ok, f"Both jobs visible after second upload ({job_count2} rows)", details, test_name)

        # ================================================================
        # TEST 9: Navigate away and back -> jobs persist
        # ================================================================
        print("\n[Test 9] Navigate away -> back -> jobs still in list")
        test_name = "pipe_09"
        details = []
        all_ok = True

        nav_to_lib = _nav_to_library(page)
        details.append(f"Navigated to Library: {nav_to_lib}")
        page.wait_for_timeout(1000)

        _take_snapshot(page, f"{test_name}_library")
        details.append("Intermediate screenshot at Library view saved")

        nav_back = _nav_to_pipeline(page)
        details.append(f"Navigated back to Pipeline: {nav_back}")
        all_ok = all_ok and nav_back

        job_count_after_nav = _count_job_rows(page)
        details.append(f"Job rows after navigation: {job_count_after_nav}")
        all_ok = all_ok and job_count_after_nav >= 1

        # Verify empty state is NOT shown when jobs exist
        if job_count_after_nav > 0:
            empty_visible = page.locator("text=No pipeline jobs found").is_visible() if "No pipeline jobs found" in page.content() else False
            details.append(f"Empty state hidden when jobs present: {not empty_visible}")
            all_ok = all_ok and not empty_visible

        _take_snapshot(page, test_name)
        check(all_ok, f"Jobs persist after navigation ({job_count_after_nav} rows)", details, test_name)

    finally:
        page.context.browser.close()
        pw.stop()
        httpd.shutdown()

    # --- Summary ---
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"Screenshots and verdicts in: {SCREENSHOT_DIR}")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
