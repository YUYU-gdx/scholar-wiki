from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('http://127.0.0.1:3000')
    page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='Chat').click()
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1200)
    page.screenshot(path='D:/Code/kn_gragh/.tmp/recon-chat.png', full_page=True)
    buttons = [x.strip() for x in page.locator('button').all_inner_texts() if x.strip()]
    texts = page.locator('body').inner_text()
    print(json.dumps({"inputs": page.locator('input, textarea').count(), "buttons": buttons[:60], "has_select_library": ('library' in texts.lower()), "body_excerpt": texts[:600]}, ensure_ascii=False))
    b.close()
