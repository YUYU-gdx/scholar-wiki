from playwright.sync_api import sync_playwright
import json, time
q = "请检索与供应链韧性相关的文献，并给出简要回答与依据。"
with sync_playwright() as p:
  b=p.chromium.launch(headless=True)
  page=b.new_page()
  page.goto('http://127.0.0.1:3000'); page.wait_for_load_state('networkidle')
  page.get_by_role('button', name='Chat').click(); page.wait_for_timeout(500)
  for n in ['probe','agent','新会话','New Session']:
    loc = page.get_by_role('button', name=n)
    if loc.count()>0:
      loc.first.click(); page.wait_for_timeout(500)
      if page.locator('textarea').count()>0: break
  if page.get_by_role('button', name='Agent').count()>0: page.get_by_role('button', name='Agent').first.click()
  page.locator('textarea').first.fill(q)
  page.get_by_role('button', name='Send').first.click()
  page.wait_for_timeout(12000)
  aside = page.locator("aside:has-text('Process Trace')")
  print(json.dumps({
    'aside_text': aside.inner_text() if aside.count() else '',
    'aside_buttons': aside.locator('button').all_inner_texts() if aside.count() else [],
    'tool_text_count': page.get_by_text('Tool Calls', exact=True).count(),
    'collapsed_text_count': page.get_by_text('Tool calls are collapsed.', exact=False).count(),
    'page_has_result_word': page.get_by_text('result', exact=False).count(),
    'page_has_返回_word': page.get_by_text('返回', exact=False).count(),
  }, ensure_ascii=False))
  page.screenshot(path='D:/Code/kn_gragh/.tmp/round-debug.png', full_page=True)
  b.close()
