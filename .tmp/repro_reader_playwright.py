from playwright.sync_api import sync_playwright
import json
import re

BASE = 'http://127.0.0.1:3000'


def body_has(page, s: str) -> bool:
    return s in page.inner_text('body')


def main():
    out = {
        'case1_same_paper_switch_type_not_reloaded': {},
        'case2_html_injection_executes': {},
        'case3_raw_id_fallback_on_500': {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(15000)

        def handle_route(route):
            url = route.request.url
            if '/literature/libraries' in url:
                return route.fulfill(status=200, content_type='application/json', body=json.dumps({
                    'libraries': [{'library_id': 'supply_chain', 'paper_count': 1, 'updated_at': '2026-05-03T00:00:00Z', 'path': 'D:/mock'}],
                    'default_library_id': 'supply_chain'
                }))
            if '/chat/sessions' in url:
                return route.fulfill(status=200, content_type='application/json', body=json.dumps({'sessions': []}))
            if '/graph/full' in url:
                return route.fulfill(status=200, content_type='application/json', body=json.dumps({
                    'meta': {'library_id': 'supply_chain', 'paper_count': 1, 'node_count': 1, 'edge_count': 0},
                    'nodes': [], 'edges': [], 'moderation_links': [], 'interaction_links': [], 'isolated_nodes': [],
                    'paper_map': {}
                }))

            m = re.search(r'/paper/([^/]+)/files', url)
            if m:
                pid = m.group(1)
                if pid == 'paper-key-1':
                    return route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'paper_id': 'paper-key-1', 'library_id': 'supply_chain',
                        'files': {
                            'markdown': {'path': 'C:/mock/p1.md', 'name': 'p1.md', 'size_bytes': 10},
                            'html': {'path': 'C:/mock/p1.html', 'name': 'p1.html', 'size_bytes': 10}
                        },
                        'default_view': 'markdown'
                    }))
                if pid == 'paper-key-2':
                    return route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'paper_id': 'paper-key-2', 'library_id': 'supply_chain',
                        'files': {
                            'html': {'path': 'C:/mock/p2.html', 'name': 'p2.html', 'size_bytes': 10}
                        },
                        'default_view': 'html'
                    }))
                if pid == 'paper-key-500':
                    return route.fulfill(status=500, content_type='application/json', body=json.dumps({'error': 'server_error'}))
                if pid == 'raw-500-ok':
                    return route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'paper_id': 'raw-500-ok', 'library_id': 'supply_chain',
                        'files': {
                            'markdown': {'path': 'C:/mock/raw500.md', 'name': 'raw500.md', 'size_bytes': 10}
                        },
                        'default_view': 'markdown'
                    }))
                return route.fulfill(status=404, content_type='application/json', body=json.dumps({'error': 'not_found'}))

            return route.fallback()

        page.route('**/*', handle_route)

        page.add_init_script("""
window.desktopShell = {
  runtime: 'electron',
  async readLocalFile(filePath) {
    return { ok: false, error: 'not used' };
  },
  async readLocalText(filePath) {
    if (filePath.endsWith('p1.md')) return { ok: true, data: 'MD_ONE_CONTENT' };
    if (filePath.endsWith('p1.html')) return { ok: true, data: '<div id="html-one">HTML_ONE_CONTENT</div>' };
    if (filePath.endsWith('p2.html')) return { ok: true, data: '<img src=x onerror="window.__xss_flag=\'TRIGGERED\'"> <div id="html-two">HTML_TWO_CONTENT</div>' };
    if (filePath.endsWith('raw500.md')) return { ok: true, data: 'RAW_500_FALLBACK_OK' };
    return { ok: false, error: 'missing:' + filePath };
  }
};
""")

        page.goto(BASE)
        page.wait_for_load_state('networkidle')

        # Case 1
        page.evaluate("window.postMessage({type:'KN_GRAPH_OPEN_READER',payload:{paperId:'paper-key-1',libraryId:'supply_chain',preferredType:'markdown',rawPaperId:'raw-1'}}, '*')")
        page.wait_for_timeout(1200)
        case1_before = body_has(page, 'MD_ONE_CONTENT') and (not body_has(page, 'HTML_ONE_CONTENT'))

        page.evaluate("window.postMessage({type:'KN_GRAPH_OPEN_READER',payload:{paperId:'paper-key-1',libraryId:'supply_chain',preferredType:'html',rawPaperId:'raw-1'}}, '*')")
        page.wait_for_timeout(1200)
        case1_md_after = body_has(page, 'MD_ONE_CONTENT')
        case1_html_after = body_has(page, 'HTML_ONE_CONTENT')
        out['case1_same_paper_switch_type_not_reloaded'] = {
            'before_markdown_only': case1_before,
            'after_switch_markdown_visible': case1_md_after,
            'after_switch_html_visible': case1_html_after,
            'reproduced': case1_before and case1_md_after and (not case1_html_after),
        }
        page.screenshot(path='D:/Code/kn_gragh/.tmp/repro_case1_same_paper_switch.png', full_page=True)

        # Case 2
        page.evaluate("window.postMessage({type:'KN_GRAPH_OPEN_READER',payload:{paperId:'paper-key-2',libraryId:'supply_chain',preferredType:'html',rawPaperId:''}}, '*')")
        page.wait_for_timeout(1500)
        xss_flag = page.evaluate('window.__xss_flag || ""')
        html_two_visible = body_has(page, 'HTML_TWO_CONTENT')
        out['case2_html_injection_executes'] = {
            'html_visible': html_two_visible,
            'xss_flag': xss_flag,
            'reproduced': html_two_visible and xss_flag == 'TRIGGERED',
        }
        page.screenshot(path='D:/Code/kn_gragh/.tmp/repro_case2_html_injection.png', full_page=True)

        # Case 3
        page.evaluate("window.postMessage({type:'KN_GRAPH_OPEN_READER',payload:{paperId:'paper-key-500',libraryId:'supply_chain',preferredType:'markdown',rawPaperId:'raw-500-ok'}}, '*')")
        page.wait_for_timeout(1500)
        raw_visible = body_has(page, 'RAW_500_FALLBACK_OK')
        err_visible = body_has(page, 'failed to resolve paper files')
        out['case3_raw_id_fallback_on_500'] = {
            'fallback_content_visible': raw_visible,
            'error_text_visible': err_visible,
            'reproduced': raw_visible and (not err_visible),
        }
        page.screenshot(path='D:/Code/kn_gragh/.tmp/repro_case3_raw_fallback.png', full_page=True)

        browser.close()

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
