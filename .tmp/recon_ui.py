from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('http://127.0.0.1:3000')
    page.wait_for_load_state('networkidle')
    page.screenshot(path='D:/Code/kn_gragh/.tmp/round1-recon.png', full_page=True)
    buttons = [x.strip() for x in page.locator('button').all_inner_texts() if x.strip()]
    inputs = page.locator('input, textarea').count()
    headings = [x.strip() for x in page.locator('h1, h2, h3').all_inner_texts() if x.strip()]
    print(json.dumps({"url": page.url, "buttons": buttons[:40], "inputs_count": inputs, "headings": headings[:20]}, ensure_ascii=False))
    b.close()
