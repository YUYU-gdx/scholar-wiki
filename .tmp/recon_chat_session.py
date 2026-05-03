from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('http://127.0.0.1:3000')
    page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='Chat').click()
    page.wait_for_timeout(500)

    # select session
    for n in ['probe','agent','新会话','New Session']:
      loc = page.get_by_role('button', name=n)
      if loc.count()>0:
        loc.first.click()
        page.wait_for_timeout(800)
        break

    page.screenshot(path='D:/Code/kn_gragh/.tmp/recon-chat-session.png', full_page=True)
    print(json.dumps({
      'inputs': page.locator('input, textarea').count(),
      'textarea': page.locator('textarea').count(),
      'send': page.get_by_role('button', name='Send').count(),
      'body_excerpt': page.locator('body').inner_text()[:800]
    }, ensure_ascii=False))
    b.close()
