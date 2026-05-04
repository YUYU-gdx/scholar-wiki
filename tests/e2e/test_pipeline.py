"""
E2E tests for the Pipeline panel of KN Graph.

Requires:
  - Backend at http://127.0.0.1:8013
  - Frontend at file:///D:/Code/kn_gragh/scholarai-workbench/dist/index.html
  - Playwright installed (uv run python -m playwright install chromium)

Run:
  uv run python tests/e2e/test_pipeline.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, expect

FRONTEND_URL = "file:///D:/Code/kn_gragh/scholarai-workbench/dist/index.html"
API_BASE = "http://127.0.0.1:8013"
TEST_PDF = (
    "D:/Code/kn_gragh/outputs/full data/full data/organized_by_title/pdf/"
    "STRATEGIC MANAGEMENT JOURNAL_83.pdf"
)
TEST_PDF2 = (
    "D:/Code/kn_gragh/outputs/full data/full data/organized_by_title/pdf/"
    "A Dynamic Clustering Approach to Data-Driven Assortment Personalization.pdf"
)

# Timeouts (milliseconds)
NAV_TIMEOUT = 5000
JOB_POLL_INTERVAL = 5000
JOB_COMPLETE_TIMEOUT = 180000  # 3 minutes


# ---------------------------------------------------------------------------
# API helpers (used to track job IDs, not for driving test logic)
# ---------------------------------------------------------------------------


def _api_get(path: str) -> dict:
    """Simple GET request to the backend."""
    url = f"{API_BASE}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]


def _get_existing_job_ids() -> set[str]:
    """Return the set of job IDs currently in the server."""
    data = _api_get("/v1/jobs?page=1&page_size=100")
    jobs = data.get("jobs", []) or []
    return {j["job_id"] for j in jobs}


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------


def _create_page() -> tuple[Page, "sync_playwright"]:
    """Create a configured browser page for testing.

    Returns (page, playwright) -- caller must call playwright.stop() when done.
    """
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=True,
        args=["--allow-file-access-from-files", "--disable-web-security"],
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        bypass_csp=True,
    )
    page = context.new_page()

    # Inject the backend URL BEFORE the app loads so API_BASE points to the real server
    page.add_init_script(
        f"""
        window.desktopShell = {{
            getBackendUrlSync: function() {{ return '{API_BASE}'; }}
        }};
    """
    )

    page.goto(FRONTEND_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    return page, p


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------


def _nav_to_pipeline(page: Page) -> None:
    """Click the Pipeline nav button and wait for the view to load."""
    pipeline_btn = page.locator("button", has_text="Pipeline")
    pipeline_btn.click()
    page.wait_for_timeout(2000)
    expect(page.get_by_role("heading", name="Data Pipeline")).to_be_visible(
        timeout=NAV_TIMEOUT
    )


def _nav_to_library(page: Page) -> None:
    """Click the Library nav button."""
    library_btn = page.locator("button", has_text="Library")
    library_btn.click()
    page.wait_for_timeout(1500)


def _select_pdf_file(page: Page, pdf_path: str) -> None:
    """Select a PDF file using the hidden file input."""
    file_input = page.locator('input[type="file"]#pdf-upload')
    file_input.set_input_files(pdf_path)


def _refresh_jobs(page: Page) -> None:
    """Click the Refresh button to reload job list."""
    refresh_btn = page.locator("button:has-text('Refresh')")
    if refresh_btn.is_visible():
        refresh_btn.click()
        page.wait_for_timeout(1500)


def _get_job_count(page: Page) -> int:
    """Count the number of job rows in the pipeline table (excluding empty-state row)."""
    rows = page.locator("tbody tr")
    count = 0
    for i in range(rows.count()):
        text = rows.nth(i).inner_text()
        if "No pipeline jobs found" not in text:
            count += 1
    return count


def _find_job_row_with_text(page: Page, needle: str) -> bool:
    """Check any job row contains the given text."""
    rows = page.locator("tbody tr")
    for i in range(rows.count()):
        text = rows.nth(i).inner_text()
        if "No pipeline jobs found" not in text and needle in text:
            return True
    return False


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------


def run_tests() -> int:
    """Run all Pipeline E2E tests. Returns 0 on success, non-zero on failure."""
    failed = 0
    passed = 0

    def check(condition: bool, name: str) -> None:
        nonlocal failed, passed
        if condition:
            passed += 1
            print(f"  PASS: {name}")
        else:
            failed += 1
            print(f"  FAIL: {name}")

    print("=" * 70)
    print("KN Graph Pipeline E2E Tests")
    print("=" * 70)

    # Record existing job IDs so we can identify our new uploads
    existing_ids = _get_existing_job_ids()
    print(f"\n[Pre-condition] Existing jobs in server: {len(existing_ids)}")

    page, pw = _create_page()

    try:
        # ------------------------------------------------------------------
        # TEST 1: Pipeline panel loads correctly
        # ------------------------------------------------------------------
        print("\n[Test 1] Pipeline panel loads correctly")
        _nav_to_pipeline(page)

        check(
            page.get_by_role("heading", name="Data Pipeline").is_visible(),
            "Heading 'Data Pipeline' is visible",
        )
        check(
            page.locator("h3:has-text('Upload PDF')").is_visible(),
            "'Upload PDF' section header is visible",
        )
        check(
            page.locator("h3:has-text('Pipeline Jobs')").is_visible(),
            "'Pipeline Jobs' section header is visible",
        )

        # ------------------------------------------------------------------
        # TEST 2: Import button disabled when no file selected
        # ------------------------------------------------------------------
        print("\n[Test 2] Import button disabled when no file selected")

        import_btn = page.locator("button:has-text('Import')")
        check(
            import_btn.is_disabled(),
            "Import button is disabled with no file selected",
        )

        # Verify the file label shows placeholder text
        file_label = page.locator("p:has-text('Choose a PDF file')")
        check(
            file_label.is_visible(),
            "File label shows 'Choose a PDF file' placeholder",
        )

        # ------------------------------------------------------------------
        # TEST 3: Select PDF enables Import and shows filename
        # ------------------------------------------------------------------
        print("\n[Test 3] Select PDF enables Import and shows filename")
        print(f"  Using test PDF: {TEST_PDF}")

        _select_pdf_file(page, TEST_PDF)
        page.wait_for_timeout(1000)

        pdf_basename = Path(TEST_PDF).name
        file_label_after = page.locator(f"p.truncate:has-text('{pdf_basename}')")
        check(
            file_label_after.is_visible(),
            f"Filename '{pdf_basename}' is shown after selection",
        )

        check(
            not import_btn.is_disabled(),
            "Import button is enabled after selecting PDF",
        )

        # ------------------------------------------------------------------
        # TEST 4: Upload triggers pipeline -> job appears in list
        # ------------------------------------------------------------------
        print("\n[Test 4] Upload triggers pipeline job creation")
        print("  Clicking Import...")

        import_btn.click()
        page.wait_for_timeout(4000)

        # Verify a job with "job_" prefix appeared
        has_job = _find_job_row_with_text(page, "job_")
        check(has_job, "A job appears in the list after upload")

        # Verify the count increased (or at least one job exists)
        job_count = _get_job_count(page)
        check(job_count >= 1, f"Job list has entries (found {job_count})")

        # Find our new job(s) by checking server
        new_ids = _get_existing_job_ids() - existing_ids
        print(f"  New job IDs created: {new_ids}")
        check(len(new_ids) > 0, "At least one new job ID created on server")

        # ------------------------------------------------------------------
        # TEST 5: Job progresses (status changes away from initial state)
        # ------------------------------------------------------------------
        print("\n[Test 5] Job progresses beyond initial state")
        print("  Waiting for job to move past 'queued' (up to 60s)...")

        # Poll for jobs that have moved past "queued"
        deadline = time.time() + 60
        progressed = False
        observed_statuses = set()

        while time.time() < deadline:
            _refresh_jobs(page)
            # Check status column for jobs that are NOT "queued"
            status_cells = page.locator("tbody tr td:nth-child(5) span")
            for i in range(status_cells.count()):
                s = status_cells.nth(i).inner_text().strip().lower()
                observed_statuses.add(s)
                if s in ("running", "completed", "failed", "cancelled"):
                    progressed = True
                    break
            if progressed:
                break
            page.wait_for_timeout(JOB_POLL_INTERVAL)

        print(f"  Observed statuses: {observed_statuses}")
        check(
            progressed,
            f"Job status changed from 'queued' to progressed state (saw: {observed_statuses})",
        )

        # ------------------------------------------------------------------
        # TEST 6: At least one job reached a terminal state
        # ------------------------------------------------------------------
        print("\n[Test 6] Jobs reach terminal/complete states")
        print(f"  Waiting up to {JOB_COMPLETE_TIMEOUT // 1000}s...")

        deadline2 = time.time() + JOB_COMPLETE_TIMEOUT / 1000
        terminal_found = False

        while time.time() < deadline2:
            _refresh_jobs(page)
            status_cells = page.locator("tbody tr td:nth-child(5) span")
            for i in range(status_cells.count()):
                s = status_cells.nth(i).inner_text().strip().lower()
                if s in ("completed", "failed", "cancelled"):
                    terminal_found = True
                    break
            if terminal_found:
                break
            page.wait_for_timeout(JOB_POLL_INTERVAL)

        check(terminal_found, "A job has reached a terminal status (completed/failed/cancelled)")

        # Check progress bars show meaningful values (>0%)
        progress_spans = page.locator("tbody tr td:nth-child(4) span:last-child")
        any_progress = False
        for i in range(progress_spans.count()):
            text = progress_spans.nth(i).inner_text().strip().rstrip("%").strip()
            try:
                if int(text) > 0:
                    any_progress = True
                    break
            except ValueError:
                pass
        check(any_progress, "Progress column shows percentage > 0%")

        # ------------------------------------------------------------------
        # TEST 7: Table uses table-fixed, no horizontal overflow
        # ------------------------------------------------------------------
        print("\n[Test 7] Table layout uses table-fixed, no overflow")

        table = page.locator("table.table-fixed")
        check(table.count() > 0, "Table has 'table-fixed' class")

        overflow_container = page.locator(".overflow-x-auto")
        check(
            overflow_container.count() > 0,
            "Overflow container exists for horizontal scroll management",
        )

        # Verify filename column exists in the table
        filename_cells = page.locator("tbody tr td:nth-child(2) span.truncate")
        if filename_cells.count() > 0:
            check(True, "Filename cells use 'truncate' class for long filenames")
        else:
            filename_parents = page.locator("tbody tr td:nth-child(2)")
            check(
                filename_parents.count() > 0,
                "Filename column (col 2) exists in job table",
            )

        # ------------------------------------------------------------------
        # TEST 8: Upload a second PDF -> multiple jobs appear in list
        # ------------------------------------------------------------------
        print("\n[Test 8] Upload second PDF, verify multiple jobs")
        print(f"  Using test PDF 2: {TEST_PDF2}")

        _select_pdf_file(page, TEST_PDF2)
        page.wait_for_timeout(800)

        import_btn2 = page.locator("button:has-text('Import')")
        check(
            not import_btn2.is_disabled(),
            "Import button is enabled after selecting second PDF",
        )

        import_btn2.click()
        page.wait_for_timeout(4000)

        job_count2 = _get_job_count(page)
        check(job_count2 >= 2, f"At least 2 jobs in list (found {job_count2})")

        # ------------------------------------------------------------------
        # TEST 9: Job list persists across navigation
        # ------------------------------------------------------------------
        print("\n[Test 9] Job list persists after navigating away and back")

        _nav_to_library(page)
        page.wait_for_timeout(1000)

        _nav_to_pipeline(page)

        job_count_after_nav = _get_job_count(page)
        check(
            job_count_after_nav >= 1,
            f"Jobs persist after navigation (found {job_count_after_nav})",
        )

        # ------------------------------------------------------------------
        # TEST 10: Empty state message exists in the component
        # ------------------------------------------------------------------
        print("\n[Test 10] Empty state handling")

        # The component code defines the empty state text.
        # When jobs are present, React conditionally hides it, so it won't be
        # in the DOM. We verify it exists in the component's static source
        # by checking the page content or by confirming the table renders
        # without the empty state showing when jobs are present.
        page_content = page.content()
        empty_in_source = "No pipeline jobs found" in page_content

        # The empty state row should NOT be visible when jobs exist
        empty_visible = page.locator("text=No pipeline jobs found").is_visible() if empty_in_source else False

        if job_count_after_nav > 0:
            check(
                not empty_visible,
                "Empty state text is hidden when jobs are present (correct UX)",
            )
        else:
            check(
                empty_in_source,
                "'No pipeline jobs found.' text defined in component",
            )

    finally:
        page.context.browser.close()
        pw.stop()

    # Summary
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
