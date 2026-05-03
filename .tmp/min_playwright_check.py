from playwright.sync_api import sync_playwright
import json, time

question = "请检索与供应链韧性相关的文献，并给出简要回答与依据。"
out = {
  "question": question,
  "answer_visible": False,
  "tool_trace_collapsed_hint_visible": False,
  "tool_entries_visible_after_expand": False,
  "args_visible_after_expand": False,
  "result_visible_after_expand": False,
  "process_trace_before": "",
  "process_trace_after": ""
}

with sync_playwright() as p:
  b = p.chromium.launch(headless=True)
  page = b.new_page()
  page.set_default_timeout(20000)
  page.goto('http://127.0.0.1:3000')
  page.wait_for_load_state('networkidle')

  page.get_by_role('button', name='Chat').click()
  page.wait_for_timeout(500)

  # open an existing session or create one
  for n in ['probe','agent','新会话','New Session']:
    loc = page.get_by_role('button', name=n)
    if loc.count() > 0:
      loc.first.click()
      page.wait_for_timeout(700)
      if page.locator('textarea').count() > 0:
        break

  if page.get_by_role('button', name='Agent').count() > 0:
    page.get_by_role('button', name='Agent').first.click()

  page.locator('textarea').first.fill(question)
  page.get_by_role('button', name='Send').first.click()

  deadline = time.time() + 120
  while time.time() < deadline:
    page.wait_for_timeout(1000)
    thinking = page.get_by_text('Thinking...', exact=False).count() > 0
    msg_blocks = page.locator("div[class*='font-serif'][class*='text-on-surface']")
    if msg_blocks.count() > 0:
      txt = msg_blocks.last.inner_text().strip()
      if txt and (not thinking) and txt.lower() != 'thinking...':
        out['answer_visible'] = True
        break

  trace = page.locator("aside:has-text('Process Trace')")
  if trace.count() > 0:
    before = trace.inner_text()
    out['process_trace_before'] = before
    out['tool_trace_collapsed_hint_visible'] = ('Tool calls are collapsed.' in before)

    # try expanding
    toggles = trace.locator('button, summary, [role="button"]')
    for i in range(min(toggles.count(), 5)):
      try:
        toggles.nth(i).click(timeout=1000)
        page.wait_for_timeout(300)
      except Exception:
        pass

    after = trace.inner_text()
    out['process_trace_after'] = after

    out['tool_entries_visible_after_expand'] = ('Tool Calls' in after) or ('tool_' in after.lower())
    out['args_visible_after_expand'] = any(k in after for k in ['args', 'arguments', '参数', '{', '"'])
    out['result_visible_after_expand'] = any(k in after.lower() for k in ['result', 'output', '返回', 'response'])

  page.screenshot(path='D:/Code/kn_gragh/.tmp/min-playwright-proof.png', full_page=True)
  b.close()

print(json.dumps(out, ensure_ascii=False))
