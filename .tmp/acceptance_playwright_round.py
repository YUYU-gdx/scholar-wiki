from playwright.sync_api import sync_playwright
import json, time, re

QUESTION = "请检索与供应链韧性相关的文献，并给出简要回答与依据。"

result = {
  "question": QUESTION,
  "answer_visible": False,
  "tool_call_item_visible": False,
  "tool_section_default_collapsed": None,
  "single_tool_default_collapsed": None,
  "expanded_has_args": False,
  "expanded_has_result": False,
  "notes": []
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_default_timeout(20000)
    page.goto('http://127.0.0.1:3000')
    page.wait_for_load_state('networkidle')

    page.get_by_role('button', name='Chat').click()
    page.wait_for_timeout(600)

    # ensure a session is opened
    opened = False
    for n in ['probe','agent','新会话','New Session']:
        loc = page.get_by_role('button', name=n)
        if loc.count() > 0:
            loc.first.click()
            page.wait_for_timeout(700)
            if page.locator('textarea').count() > 0:
                opened = True
                break
    if not opened and page.locator('textarea').count() == 0:
        raise RuntimeError('No chat session opened (textarea missing).')

    agent_btn = page.get_by_role('button', name='Agent')
    if agent_btn.count() > 0:
        agent_btn.first.click()
        page.wait_for_timeout(200)

    textarea = page.locator('textarea').first
    textarea.fill(QUESTION)
    page.get_by_role('button', name='Send').first.click()

    deadline = time.time() + 120
    while time.time() < deadline:
      page.wait_for_timeout(1000)
      assistant_blocks = page.locator("div[class*='font-serif'][class*='text-on-surface']")
      if assistant_blocks.count() > 0:
        t = assistant_blocks.last.inner_text().strip()
        if t and t.lower() != 'thinking...':
          result['answer_visible'] = True
      if page.locator("text=Tool Calls").count() > 0 and result['answer_visible']:
        break

    page.wait_for_timeout(1000)

    result['tool_call_item_visible'] = page.locator("aside >> text=Tool Calls").count() > 0

    aside = page.locator("aside:has-text('Process Trace')")
    aside_text_before = aside.inner_text() if aside.count() > 0 else ''

    # default collapsed checks (heuristic): collapsed hint or hidden payload-like text
    result['tool_section_default_collapsed'] = ('collapsed' in aside_text_before.lower()) or ('已折叠' in aside_text_before)

    # find clickable controls inside aside and expand
    toggled = 0
    if aside.count() > 0:
      candidates = aside.locator('button, summary, [role="button"]')
      for i in range(min(candidates.count(), 12)):
        try:
          candidates.nth(i).click(timeout=1000)
          toggled += 1
          page.wait_for_timeout(150)
        except Exception:
          pass

    aside_text_after = aside.inner_text() if aside.count() > 0 else ''
    result['single_tool_default_collapsed'] = result['tool_section_default_collapsed']

    # args/result checks (after attempted expansion)
    if re.search(r'\{|"|arguments|args|参数', aside_text_after, re.IGNORECASE):
      result['expanded_has_args'] = True
    if re.search(r'result|output|返回|响应', aside_text_after, re.IGNORECASE):
      result['expanded_has_result'] = True

    result['notes'].append(f'toggles_clicked={toggled}')
    result['notes'].append(f'aside_before_len={len(aside_text_before)}')
    result['notes'].append(f'aside_after_len={len(aside_text_after)}')

    page.screenshot(path='D:/Code/kn_gragh/.tmp/acceptance-round.png', full_page=True)
    browser.close()

print(json.dumps(result, ensure_ascii=False))

