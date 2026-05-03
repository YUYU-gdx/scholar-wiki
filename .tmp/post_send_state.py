from playwright.sync_api import sync_playwright
import json, time
q='请检索与供应链韧性相关的文献，并给出简要回答与依据。'
with sync_playwright() as p:
  b=p.chromium.launch(headless=True)
  page=b.new_page()
  page.goto('http://127.0.0.1:3000'); page.wait_for_load_state('networkidle')
  page.get_by_role('button', name='Chat').click(); page.wait_for_timeout(500)
  for n in ['probe','agent','新会话','New Session']:
    loc=page.get_by_role('button', name=n)
    if loc.count()>0:
      loc.first.click(); page.wait_for_timeout(600)
      if page.locator('textarea').count()>0: break
  if page.get_by_role('button', name='Agent').count()>0: page.get_by_role('button', name='Agent').first.click()
  page.locator('textarea').first.fill(q)
  page.get_by_role('button', name='Send').first.click()
  page.wait_for_timeout(25000)
  body=page.locator('body').inner_text()
  print(json.dumps({
    'has_thinking': 'Thinking' in body,
    'has_failed_cn': '失败' in body,
    'has_error_en': 'error' in body.lower(),
    'has_tool_calls': 'Tool Calls' in body,
    'has_collapsed': 'Tool calls are collapsed.' in body,
    'excerpt': body[:1500]
  }, ensure_ascii=False))
  b.close()
