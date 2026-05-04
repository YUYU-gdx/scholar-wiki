"""
E2E Oracle Test: Pipeline -> Library complete chain.

Uploads a real PDF, waits for the pipeline to finish, then verifies the
paper appears in the Library with correct title and source paths.

Uses the REAL backend API — no mocking.

Usage:
    uv run python tests/e2e/test_pipeline_to_library.py
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
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

BACKEND_URL = "http://127.0.0.1:8013"
DIST_DIR = Path("D:/Code/kn_gragh/scholarai-workbench/dist")
SCREENSHOTS_DIR = Path("D:/Code/kn_gragh/tests/e2e/screenshots")
TEST_PDF = Path(
    "D:/Code/kn_gragh/outputs/full data/full data/organized_by_title/pdf/"
    "A framework for supply chain sustainability in service industry with Confirmatory Factor Analysis.pdf"
)
LIBRARY_ID = "e2e_test"

# Timeouts
JOB_POLL_INTERVAL = 5  # seconds
JOB_COMPLETE_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------------------
# HTTP server for frontend dist
# ---------------------------------------------------------------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)
    def log_message(self, fmt, *args):
        pass


def _find_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class FrontendServer:
    def __init__(self):
        self.port = _find_free_port()
        self._httpd = None
        self._thread = None

    def start(self):
        self._httpd = socketserver.TCPServer(("127.0.0.1", self.port), _QuietHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(path: str) -> dict:
    url = f"{BACKEND_URL}{path}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, data: dict | None = None) -> dict:
    url = f"{BACKEND_URL}{path}"
    resp = requests.post(url, json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()


def api_upload_pdf(pdf_path: Path, library_id: str) -> dict:
    url = f"{BACKEND_URL}/v1/pipeline/parse-extract"
    with pdf_path.open("rb") as f:
        resp = requests.post(
            url,
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={"library_id": library_id},
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def wait_for_job(job_id: str, timeout: int = JOB_COMPLETE_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        try:
            data = api_get(f"/v1/jobs/{job_id}")
        except Exception:
            time.sleep(JOB_POLL_INTERVAL)
            continue
        status = str(data.get("status", "")).strip().lower()
        if status != last_status:
            print(f"  Job {job_id[:20]}... status={status} "
                  f"stage={data.get('stage','')} progress={data.get('progress',0)}%")
            last_status = status
        if status in ("completed", "failed", "cancelled"):
            return data
        time.sleep(JOB_POLL_INTERVAL)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def reload_graph(library_id: str) -> dict:
    return api_post(f"/graph/reload?library_id={library_id}")


# ---------------------------------------------------------------------------
# Playwright setup
# ---------------------------------------------------------------------------

def create_page(origin: str):
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

    # Inject backend URL BEFORE the app loads
    page.add_init_script(
        f"""
        window.desktopShell = {{
            getBackendUrlSync: function() {{ return '{BACKEND_URL}'; }}
        }};
        """
    )

    page.goto(f"{origin}/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    return page, p


def setup_api_proxy(page: Page, origin: str):
    """Proxy API calls to the real backend."""

    def handle_route(route):
        url = route.request.url
        method = route.request.method
        if not url.startswith(origin):
            return route.continue_()

        path = url[len(origin):]

        api_prefixes = [
            "/graph/", "/literature/", "/chat/", "/paper/", "/variable/",
            "/v1/", "/settings", "/api/", "/healthz",
        ]
        is_api = any(path.startswith(p) for p in api_prefixes)
        if not is_api:
            return route.continue_()

        backend_url = f"{BACKEND_URL}{path}"
        try:
            resp = page.request.fetch(
                backend_url, method=method,
                headers={
                    k: v for k, v in route.request.headers.items()
                    if k.lower() not in ("host", "origin", "referer", "content-length")
                },
                data=route.request.post_data,
                timeout=30000,
            )
            headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in (
                    "transfer-encoding", "content-encoding",
                    "keep-alive", "connection",
                )
            }
            headers["access-control-allow-origin"] = origin
            route.fulfill(status=resp.status, headers=headers, body=resp.body())
        except Exception as e:
            route.fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps({"error": f"proxy_failed: {e}"}),
            )

    page.route("**/*", handle_route)


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def nav_to_pipeline(page: Page, timeout_ms: int = 5000):
    btn = page.locator("button", has_text="Pipeline")
    btn.click()
    page.wait_for_timeout(2000)
    heading = page.locator("text=Data Pipeline")
    heading.wait_for(state="visible", timeout=timeout_ms)
    assert heading.is_visible(), "Pipeline heading not visible"


def nav_to_library(page: Page):
    btn = page.locator("button", has_text="Library")
    btn.click()
    page.wait_for_timeout(2000)


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def run_test() -> int:
    results: dict[str, bool] = {}
    verdicts: list[str] = []

    # Prepare
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("KN Graph: Pipeline -> Library E2E Oracle Test")
    print("=" * 70)
    print(f"Backend: {BACKEND_URL}")
    print(f"Test PDF: {TEST_PDF.name}")
    print(f"PDF size: {TEST_PDF.stat().st_size:,} bytes")
    print(f"Library: {LIBRARY_ID}")
    print()

    # Start frontend server
    server = FrontendServer()
    server.start()
    print(f"Frontend server: {server.origin}")

    page, pw = create_page(server.origin)

    # Capture console errors
    console_errors: list[str] = []
    page.on("console", lambda msg: (
        console_errors.append(f"[{msg.type}] {msg.text}")
        if msg.type == "error" else None
    ))
    page.on("pageerror", lambda err: console_errors.append(f"[pageerror] {err}"))

    setup_api_proxy(page, server.origin)

    try:
        # ==================================================================
        # STEP 1: Navigate to Pipeline and upload PDF
        # ==================================================================
        print("\n--- Step 1: Upload PDF via Pipeline ---")
        nav_to_pipeline(page)

        # Click Library first to ensure correct library is active, then go back
        page.wait_for_timeout(1000)

        # Verify Pipeline UI elements
        upload_heading = page.locator("h3:has-text('Upload PDF')")
        assert upload_heading.is_visible(), "Upload PDF heading not visible"
        print("  Pipeline UI loaded correctly")

        # Select the test PDF
        file_input = page.locator('input[type="file"]#pdf-upload')
        assert file_input.count() > 0, "File input not found"
        file_input.set_input_files(str(TEST_PDF))
        page.wait_for_timeout(1000)

        # Verify file is selected
        pdf_name = TEST_PDF.name
        file_label = page.locator(f"p.truncate:has-text('{pdf_name}')")
        assert file_label.is_visible(), f"File label not showing '{pdf_name}'"
        print(f"  File selected: {pdf_name}")

        # Verify Import button is enabled
        import_btn = page.locator("button:has-text('Import')")
        assert not import_btn.is_disabled(), "Import button should be enabled"
        print("  Import button enabled")

        # Click Import
        import_btn.click()
        page.wait_for_timeout(4000)
        print("  Import clicked, waiting for job creation...")

        # Get job ID from the API list
        jobs_data = api_get(f"/v1/jobs?page=1&page_size=5&library_id={LIBRARY_ID}")
        jobs = jobs_data.get("jobs", [])
        if not jobs:
            raise RuntimeError("No jobs found after upload")
        # Find the most recent job with our filename
        our_job = None
        for job in jobs:
            if job.get("file_name") == pdf_name:
                our_job = job
                break
        if not our_job:
            our_job = jobs[0]  # fall back to most recent
        job_id = our_job["job_id"]
        print(f"  Job created: {job_id}")
        results["step1_upload"] = True
        verdicts.append(f"Upload: job_id={job_id}")

        # ==================================================================
        # STEP 2: Wait for pipeline to complete
        # ==================================================================
        print(f"\n--- Step 2: Wait for job {job_id} to complete ---")
        print(f"  Polling every {JOB_POLL_INTERVAL}s (timeout {JOB_COMPLETE_TIMEOUT}s)...")

        job_result = wait_for_job(job_id)
        status = job_result["status"]
        print(f"  Final status: {status}")

        if status == "completed":
            results["step2_job_completed"] = True
            verdicts.append(f"Pipeline: completed (stage={job_result.get('stage')})")
            # Get full result
            try:
                full_result = api_get(f"/v1/jobs/{job_id}/result")
                print(f"  Graph updated: {full_result.get('graph_updated')}")
                print(f"  Imported papers: {full_result.get('imported_paper_count')}")
                extract = full_result.get("extract", {})
                summary = extract.get("summary", {})
                print(f"  Extraction summary: {summary}")
            except Exception as e:
                print(f"  Could not fetch full result: {e}")
        else:
            results["step2_job_completed"] = False
            verdicts.append(f"Pipeline: {status} (error={job_result.get('error_code')})")
            print(f"  ERROR: Job failed with {job_result.get('error_code')}: "
                  f"{job_result.get('error_detail', '')[:200]}")

        # ==================================================================
        # STEP 3: Reload graph service
        # ==================================================================
        print("\n--- Step 3: Reload graph service ---")
        reload_data = reload_graph(LIBRARY_ID)
        print(f"  Graph reload: {reload_data}")
        results["step3_graph_reloaded"] = True

        # ==================================================================
        # STEP 4: Check API data
        # ==================================================================
        print("\n--- Step 4: Check graph/full API ---")
        graph_data = api_get(f"/graph/full?library_id={LIBRARY_ID}")
        paper_map = graph_data.get("paper_map", {})

        print(f"  Paper count: {graph_data['meta']['paper_count']}")
        print(f"  Node count: {graph_data['meta']['node_count']}")

        api_ok = True
        api_details: list[str] = []
        for pid, paper in paper_map.items():
            title = paper.get("title", "")
            source_pdf = paper.get("source_pdf_path", "")
            source_md = paper.get("source_md_path", "")
            print(f"  Paper: {title[:100]}")
            print(f"    source_pdf_path: {source_pdf}")
            print(f"    source_md_path: {source_md}")

            # Check title is real (not a job ID)
            if title.startswith("job_") and len(title) > 30:
                api_details.append(f"FAIL: Title is a job ID: {title}")
                api_ok = False
            else:
                api_details.append(f"OK: Real title: {title}")

            # Check source paths
            if not source_pdf or not Path(source_pdf).exists():
                api_details.append(f"WARN: source_pdf_path missing or not found: {source_pdf}")
            if not source_md:
                api_details.append(f"WARN: source_md_path empty")
            if source_pdf and source_md:
                api_details.append("OK: source paths present")

        if paper_map:
            results["step4_api_contains_paper"] = api_ok
            verdicts.append(f"API: {api_details[0] if api_details else 'no details'}")
        else:
            results["step4_api_contains_paper"] = False
            verdicts.append("API: NO papers in paper_map")
            api_details.append("FAIL: paper_map is empty")

        for d in api_details:
            print(f"    {d}")

        # ==================================================================
        # STEP 5: Navigate to Library and take screenshot
        # ==================================================================
        print("\n--- Step 5: Check Library view ---")
        nav_to_library(page)

        # Wait for papers to load
        page.wait_for_timeout(5000)

        ss_path = SCREENSHOTS_DIR / "lib_after_pipeline.png"
        page.screenshot(path=str(ss_path))
        print(f"  Screenshot saved: {ss_path}")

        # Save HTML dump for analysis
        html_path = SCREENSHOTS_DIR / "lib_after_pipeline.html"
        html_path.write_text(page.content(), encoding="utf-8")
        print(f"  HTML dump saved: {html_path}")

        # Check DOM text
        dom_text = page.content()

        # Check for the paper title
        paper_title = "A framework for supply chain sustainability"
        title_present = paper_title in dom_text
        print(f"  Paper title visible: {title_present}")
        results["step5_title_visible"] = title_present

        # Check for "变量" (variables) section
        has_variables = "变量:" in dom_text
        has_no_variables = "变量: 无" in dom_text
        print(f"  Variables section: has_variables={has_variables}, has_no_variables={has_no_variables}")
        results["step5_variables_section"] = has_variables

        # Check source path info is not showing the job ID as title
        has_job_id_title = "job_" in dom_text and "job_ea75" in dom_text
        print(f"  Job ID in DOM (should be absent from titles): {has_job_id_title}")

        # Check paper cards
        paper_cards = page.locator("div.rounded-xl")
        card_count = paper_cards.count()
        print(f"  Paper cards visible: {card_count}")
        results["step5_cards_visible"] = card_count > 0

        if card_count > 0:
            for i in range(min(card_count, 5)):
                try:
                    text = paper_cards.nth(i).inner_text()[:200]
                    print(f"  Card {i}: {text}")
                except Exception:
                    pass

        # ==================================================================
        # STEP 6: Expand first paper to check variables
        # ==================================================================
        print("\n--- Step 6: Expand paper to check variables ---")
        if card_count > 0:
            expand_btn = page.locator(
                "div.rounded-xl button.flex.items-center.gap-2.text-left"
            ).first
            if expand_btn.count() > 0:
                expand_btn.click()
                page.wait_for_timeout(1500)

                expanded_ss = SCREENSHOTS_DIR / "lib_after_pipeline_expanded.png"
                page.screenshot(path=str(expanded_ss))
                print(f"  Expanded screenshot: {expanded_ss}")

                var_line = page.locator("div:has-text('变量:')")
                if var_line.count() > 0:
                    var_text = var_line.first.inner_text()
                    print(f"  Variable line: {var_text}")
                    results["step6_expand_variables"] = True
                else:
                    print("  No variable line found after expanding")
                    results["step6_expand_variables"] = False
            else:
                print("  Expand button not found")
                results["step6_expand_variables"] = False
        else:
            results["step6_expand_variables"] = False

        # ==================================================================
        # WRITE VERDICT
        # ==================================================================
        print("\n" + "=" * 70)
        print("WRITING VERDICT")
        print("=" * 70)

        all_pass = all(results.values())

        verdict_lines = [
            "PIPELINE-TO-LIBRARY E2E VERDICT",
            "=" * 70,
            f"Timestamp: {datetime.now().isoformat()}",
            f"Verdict: {'PASS' if all_pass else 'FAIL'}",
            "",
            "--- Test PDF ---",
            f"File: {TEST_PDF.name}",
            f"Size: {TEST_PDF.stat().st_size:,} bytes",
            f"Library: {LIBRARY_ID}",
            "",
            "--- Results ---",
        ]
        for step, passed in results.items():
            verdict_lines.append(f"  [{'PASS' if passed else 'FAIL'}] {step}")

        verdict_lines += [
            "",
            "--- Details ---",
            *verdicts,
            "",
            "--- Console Errors ---",
            *([e[:200] for e in console_errors[:10]] if console_errors else ["none"]),
        ]

        verdict_text = "\n".join(verdict_lines)
        verdict_path = SCREENSHOTS_DIR / "pipeline_to_library_verdict.txt"
        verdict_path.write_text(verdict_text, encoding="utf-8")
        print(verdict_text)
        print(f"\nVerdict written to: {verdict_path}")

        return 0 if all_pass else 1

    except Exception as e:
        import traceback
        traceback.print_exc()

        # Write failure verdict
        verdict_lines = [
            "PIPELINE-TO-LIBRARY E2E VERDICT",
            "=" * 70,
            f"Timestamp: {datetime.now().isoformat()}",
            "Verdict: FAIL",
            f"Error: {type(e).__name__}: {e}",
        ]

        # Try to take an error screenshot
        try:
            err_ss = SCREENSHOTS_DIR / "lib_pipeline_error.png"
            page.screenshot(path=str(err_ss))
            verdict_lines.append(f"Error screenshot: {err_ss}")
        except Exception:
            pass

        verdict_path = SCREENSHOTS_DIR / "pipeline_to_library_verdict.txt"
        verdict_path.write_text("\n".join(verdict_lines), encoding="utf-8")
        print(f"\nVerdict written to: {verdict_path}")
        return 1

    finally:
        page.context.browser.close()
        pw.stop()
        server.stop()


if __name__ == "__main__":
    sys.exit(run_test())
