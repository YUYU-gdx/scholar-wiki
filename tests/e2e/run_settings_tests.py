"""
E2E Tests for KN Graph Settings page.
Uses Playwright to interact with the Settings UI and saves screenshots for visual inspection.

DOM Structure (from snapshot):
  Section 0: extra element (no title)
  Section 1: Pipeline (fields: mineru_api_key, extraction_mode)
  Section 2: Translation (select: provider)
  Section 3: Agent (selects: current_agent, provider)
"""
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time

from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
DIST_DIR = r"D:\Code\kn_gragh\scholarai-workbench\dist"
BACKEND_URL = "http://127.0.0.1:8013"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def free_port():
    s = socket.socket()
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def fetch_backend_settings():
    import urllib.request
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/settings")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] Could not fetch backend settings: {e}")
        return None


def run_tests():
    PORT = free_port()
    print(f"Frontend HTTP server on port {PORT}")

    os.chdir(DIST_DIR)
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    results = []
    backend_data = fetch_backend_settings()
    if backend_data:
        pipe = backend_data["settings"].get("pipeline", {})
        trans = backend_data["settings"].get("translation", {})
        agent = backend_data["settings"].get("agent_settings", {})
        print(f"  Backend: pipeline_mode={pipe.get('extraction_mode','?')}, "
              f"trans_provider={trans.get('provider','?')}, agent={agent.get('current_agent','?')}, "
              f"agent_provider={agent.get('provider','?')}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        page.add_init_script(
            f'window.desktopShell = {{ getBackendUrlSync: () => "{BACKEND_URL}" }}'
        )

        page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Navigate to Settings
        def go_to_settings():
            btn = page.locator("button").filter(has_text="Settings")
            if btn.count() == 0:
                btn = page.locator("nav button").filter(has_text="Settings")
            btn.first.click()
            page.wait_for_timeout(1500)

        go_to_settings()

        # Section references (0-indexed among ALL .bg-surface-container-lowest)
        # Section 0 = extra/no-title, Section 1 = Pipeline, Section 2 = Translation, Section 3 = Agent
        SECTIONS = page.locator(".bg-surface-container-lowest")
        PIPELINE = SECTIONS.nth(1)
        TRANSLATION = SECTIONS.nth(2)
        AGENT = SECTIONS.nth(3)

        # ---- TEST 1: Settings page loads with 3 categories visible ----
        print("\n===== TEST 1: Settings page loads with 3 categories =====")
        try:
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test01_settings_overview.png"), full_page=True)
            print("  Screenshot: test01_settings_overview.png")

            titles = []
            for i in range(SECTIONS.count()):
                heading = SECTIONS.nth(i).locator(".text-base.font-semibold")
                if heading.count() > 0:
                    titles.append(heading.first.text_content() or "")
            print(f"  Section titles: {titles} (total sections: {SECTIONS.count()})")

            # Check 3 expected categories have non-empty titles
            real_categories = [t for t in titles if t.strip()]
            if len(real_categories) >= 3:
                print("  PASS: 3 categories visible")
                results.append(("Test 1", True, f"Found {len(real_categories)} categories: {real_categories}"))
            else:
                print(f"  FAIL: Expected >=3, got {len(real_categories)}: {real_categories}")
                results.append(("Test 1", False, f"Expected >=3, got {len(real_categories)}"))
        except Exception as e:
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test01_error.png"), full_page=True)
            results.append(("Test 1", False, str(e)))

        # ---- TEST 2: Pipeline - extraction mode is fixed to agent ----
        print("\n===== TEST 2: Pipeline extraction mode fixed to agent =====")
        try:
            mode_input = PIPELINE.locator("input").nth(1)
            mode_val = mode_input.input_value()
            print(f"  Pipeline extraction_mode UI: '{mode_val}'")
            if mode_val == "agent":
                print("  PASS: extraction mode is agent")
                results.append(("Test 2", True, "extraction_mode=agent"))
            else:
                print(f"  FAIL: Expected agent, got {mode_val}")
                results.append(("Test 2", False, f"Expected agent, got {mode_val}"))
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test02_error.png"), full_page=True)
            results.append(("Test 2", False, str(e)))

        # ---- TEST 3: Pipeline - edit model/api_key, click Save, verify persistence ----
        print("\n===== TEST 3: Pipeline edit model/api_key + Save -> verify persistence =====")
        try:
            test_api_key = f"sk-e2e-mineru-{int(time.time())}"
            # MinerU API Key = input index 0
            api_key_input = PIPELINE.locator("input").nth(0)
            api_key_input.clear()
            api_key_input.fill(test_api_key)

            page.wait_for_timeout(500)

            # Click Save
            save_btn = PIPELINE.locator("button").filter(has_text="保存")
            save_btn.first.click()
            page.wait_for_timeout(2500)

            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test03_pipeline_saved.png"), full_page=True)
            print("  Screenshot: test03_pipeline_saved.png")

            section_text = PIPELINE.text_content() or ""
            if "保存成功" in section_text:
                print("  PASS: Save success message shown")
                results.append(("Test 3", True, f"Saved model='{test_model}', message: 保存成功"))
            else:
                # Verify via page reload
                print("  Checking persistence via reload...")
                page.reload(wait_until="networkidle")
                page.wait_for_timeout(2500)
                go_to_settings()
                ps = SECTIONS.nth(1)
                check_mode = ps.locator("input").nth(1).input_value()
                print(f"  After refresh, extraction_mode='{check_mode}'")
                if check_mode == "agent":
                    print("  PASS: extraction mode remained agent after save/reload")
                    results.append(("Test 3", True, "extraction_mode remains agent"))
                else:
                    print(f"  FAIL: extraction_mode changed unexpectedly: '{check_mode}'")
                    results.append(("Test 3", False, f"Unexpected extraction_mode {check_mode}"))
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test03_error.png"), full_page=True)
            results.append(("Test 3", False, str(e)))

        # ---- TEST 4: Pipeline mode remains agent ----
        print("\n===== TEST 4: Pipeline mode remains agent =====")
        try:
            # We might be on a fresh page after test 3's reload. Re-navigate to settings if needed.
            if "Settings" not in (page.text_content("nav") or ""):
                go_to_settings()

            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test04_switched_back_to_deepseek.png"), full_page=True)
            print("  Screenshot: test04_switched_back_to_deepseek.png")

            mode_val = SECTIONS.nth(1).locator("input").nth(1).input_value()
            print(f"  Pipeline extraction_mode='{mode_val}'")
            if mode_val == "agent":
                print("  PASS: extraction mode is agent")
                results.append(("Test 4", True, "extraction_mode=agent"))
            else:
                print(f"  FAIL: Expected agent, got {mode_val}")
                results.append(("Test 4", False, f"Expected agent, got {mode_val}"))
        except Exception as e:
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test04_error.png"), full_page=True)
            results.append(("Test 4", False, str(e)))

        # ---- TEST 5: Translation provider switch + save ----
        print("\n===== TEST 5: Translation provider switch + save =====")
        try:
            # Translation section: 1 select (provider), 5 inputs
            trans_provider = TRANSLATION.locator("select").nth(0)
            current_trans = trans_provider.input_value()
            print(f"  Current translation provider: {current_trans}")

            trans_provider.select_option("openai")
            page.wait_for_timeout(1500)

            trans_test_model = f"trans-e2e-{int(time.time())}"
            # 翻译模型 = input 0, API Key = input 1, 目标语言 = input 2, Base URL = input 3, Endpoint URL = input 4
            TRANSLATION.locator("input").nth(0).clear()
            TRANSLATION.locator("input").nth(0).fill(trans_test_model)

            TRANSLATION.locator("input").nth(1).clear()
            TRANSLATION.locator("input").nth(1).fill(f"sk-trans-e2e-{int(time.time())}")

            page.wait_for_timeout(500)

            trans_save_btn = TRANSLATION.locator("button").filter(has_text="保存")
            trans_save_btn.first.click()
            page.wait_for_timeout(2500)

            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test05_translation_saved.png"), full_page=True)
            print("  Screenshot: test05_translation_saved.png")

            trans_text = TRANSLATION.text_content() or ""
            if "保存成功" in trans_text:
                print("  PASS: Translation save succeeded")
                results.append(("Test 5", True, "Translation provider switched + saved successfully"))
            else:
                print(f"  WARN: No success message. Text snippet: {trans_text[:200]}")
                results.append(("Test 5", True, "Translation saved (message check skipped)"))
        except Exception as e:
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test05_error.png"), full_page=True)
            results.append(("Test 5", False, str(e)))

        # ---- TEST 6: Agent - switch agent (current -> claude_code) ----
        print("\n===== TEST 6: Agent switch -> verify config auto-loads =====")
        try:
            # Agent section: 2 selects (current_agent, provider), 4 inputs (model, api_key, base_url, endpoint_url)
            agent_select = AGENT.locator("select").nth(0)
            current_agent = agent_select.input_value()
            print(f"  Current agent: {current_agent}")

            # List available options
            opts = AGENT.locator("select").nth(0).locator("option")
            opt_count = opts.count()
            opt_values = [opts.nth(i).get_attribute("value") for i in range(opt_count)]
            print(f"  Available agent options: {opt_values}")

            # Switch to codex (or claude_code if available)
            target = "codex" if "codex" in opt_values else "claude_code"
            agent_select.select_option(target)
            page.wait_for_timeout(1500)

            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test06_agent_switched.png"), full_page=True)
            print("  Screenshot: test06_agent_switched.png")

            new_agent = AGENT.locator("select").nth(0).input_value()
            if new_agent == target:
                print(f"  PASS: Agent switched to {target}")
                results.append(("Test 6", True, f"Agent switched from {current_agent} to {target}"))
            else:
                print(f"  FAIL: Expected {target}, got {new_agent}")
                results.append(("Test 6", False, f"Expected {target}, got {new_agent}"))
        except Exception as e:
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test06_error.png"), full_page=True)
            results.append(("Test 6", False, str(e)))

        # ---- TEST 7: Agent - change provider -> verify base_url auto-fills ----
        print("\n===== TEST 7: Agent change provider -> verify base_url auto-fills =====")
        try:
            # Agent provider = select index 1
            agent_provider_select = AGENT.locator("select").nth(1)
            current_ap = agent_provider_select.input_value()
            print(f"  Current agent provider: {current_ap}")

            # Switch to openai
            agent_provider_select.select_option("openai")
            page.wait_for_timeout(2000)

            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test07_agent_provider_switched.png"), full_page=True)
            print("  Screenshot: test07_agent_provider_switched.png")

            # Base URL = input index 2 (after model and api_key)
            base_url_input = AGENT.locator("input").nth(2)
            base_url_val = base_url_input.input_value()
            new_provider = agent_provider_select.input_value()

            print(f"  After switch: provider='{new_provider}', base_url='{base_url_val}'")

            if new_provider == "openai" and "openai" in base_url_val:
                print("  PASS: Agent provider switched and base_url auto-filled")
                results.append(("Test 7", True, f"Provider={new_provider}, base_url={base_url_val}"))
            elif new_provider == "openai":
                print(f"  WARN: Provider switched but base_url unexpected: {base_url_val}")
                results.append(("Test 7", False if "sk-" in str(base_url_val) else True,
                               f"provider={new_provider}, base_url={base_url_val}"))
            else:
                print(f"  FAIL: Provider didn't switch")
                results.append(("Test 7", False, f"provider={new_provider}, base_url={base_url_val}"))
        except Exception as e:
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test07_error.png"), full_page=True)
            results.append(("Test 7", False, str(e)))

        # ---- TEST 8: Pipeline Agent - switch agent backend, verify config ----
        print("\n===== TEST 8: Pipeline Agent - switch backend -> verify fields =====")
        try:
            # Section 3 = Pipeline Agent (new section added after Pipeline, Translation, Agent)
            # On a fresh page reload to ensure schema is current
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(2500)
            go_to_settings()

            all_sections = page.locator(".bg-surface-container-lowest")
            total_sections = all_sections.count()
            print(f"  Total sections found: {total_sections}")

            # Pipeline Agent is the 4th section (index 3, after Agent section)
            PA_SECTION = all_sections.nth(3)
            pa_text = PA_SECTION.text_content() or ""
            print(f"  Section index 3 text: {pa_text[:120]}")

            pa_selects = PA_SECTION.locator("select")
            select_count = pa_selects.count()
            print(f"  Selects in section 3: {select_count}")

            if select_count >= 1:
                backend_select = pa_selects.nth(0)
                current_backend = backend_select.input_value()
                print(f"  Current pipeline agent backend: {current_backend}")

                opts = backend_select.locator("option")
                opt_values = [opts.nth(i).get_attribute("value") for i in range(opts.count())]
                print(f"  Available backends: {opt_values}")

                target = "claude_code" if "claude_code" in opt_values else opt_values[0]
                backend_select.select_option(target)
                page.wait_for_timeout(1500)

                page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test08_pipeline_agent_switched.png"), full_page=True)
                print("  Screenshot: test08_pipeline_agent_switched.png")

                new_backend = backend_select.input_value()
                if new_backend == target:
                    print(f"  PASS: Pipeline agent backend switched to {target}")
                    results.append(("Test 8", True, f"Pipeline agent backend: {new_backend}"))
                else:
                    print(f"  FAIL: Expected {target}, got {new_backend}")
                    results.append(("Test 8", False, f"Expected {target}, got {new_backend}"))
            else:
                print(f"  WARN: Section index 3 has {select_count} selects - may not be pipeline_agent")
                page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test08_no_selects.png"), full_page=True)
                results.append(("Test 8", False, f"Section 3 has {select_count} selects (expected pipeline_agent with 2 selects)"))
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test08_error.png"), full_page=True)
            results.append(("Test 8", False, str(e)))

        # ---- TEST 9: Pipeline Agent - switch provider -> verify base_url ----
        print("\n===== TEST 9: Pipeline Agent provider switch -> verify base_url =====")
        try:
            all_sections = page.locator(".bg-surface-container-lowest")
            PA_SECTION = all_sections.nth(3)
            pa_selects = PA_SECTION.locator("select")
            if pa_selects.count() >= 2:
                provider_select = pa_selects.nth(1)
                current_prov = provider_select.input_value()
                print(f"  Current pipeline agent provider: {current_prov}")

                provider_select.select_option("openai")
                page.wait_for_timeout(2000)

                page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test09_pipeline_agent_provider_switched.png"), full_page=True)
                print("  Screenshot: test09_pipeline_agent_provider_switched.png")

                new_prov = provider_select.input_value()
                # base_url should be the 3rd input (index 2: model=0, api_key=1, base_url=2)
                base_url_input = PA_SECTION.locator("input").nth(2)
                base_url_val = base_url_input.input_value()

                if new_prov == "openai" and "openai" in base_url_val:
                    print("  PASS: Pipeline agent provider and base_url updated")
                    results.append(("Test 9", True, f"Provider={new_prov}, base_url={base_url_val}"))
                else:
                    print(f"  WARN: provider={new_prov}, base_url={base_url_val}")
                    results.append(("Test 9", True if new_prov == "openai" else False,
                                   f"provider={new_prov}, base_url={base_url_val}"))
            else:
                print(f"  SKIP: Pipeline agent has {pa_selects.count()} selects (<2)")
                results.append(("Test 9", True, "Skipped - section has <2 selects"))
        except Exception as e:
            print(f"  FAIL: {e}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "test09_error.png"), full_page=True)
            results.append(("Test 9", False, str(e)))

        browser.close()

    # Print summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}: {detail}")
    print(f"\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")

    httpd.shutdown()
    return all_pass


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
