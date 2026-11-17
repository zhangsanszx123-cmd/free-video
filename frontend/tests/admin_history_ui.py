"""Read-only existing history aggregation, built :8000 frontend; all APIs mocked."""
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

SHOTS = Path('.runtime/admin-history-ui')
SHOTS.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        page = browser.new_page(viewport=dict(width=width, height=900))
        state = dict(fail=False, role='superadmin')
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def api(route):
            url = urlparse(route.request.url)
            if url.path == '/api/admin/auth/me':
                return route.fulfill(json={'admin': dict(id=1, username='owner', nickname='管理员', role=state['role'], status='active')})
            if url.path == '/api/auth/me': return route.fulfill(json={'user': None})
            if url.path == '/api/admin/history':
                if state['fail']: return route.fulfill(status=503, json={'detail': '暂时无法加载记录'})
                query = parse_qs(url.query)
                status = query.get('status', ['all'])[0]
                rows = [dict(id=str(i), user_id=100+i%2, user_email=f'member{i%2}@example.com', title=f'知识视频 {i:02}', platform='B站',
                             status='done' if i%2 == 0 else 'error', duration_seconds=120,
                             url='javascript:window.hacked=true', created_at='2026-11-17T02:00:00Z',
                             payload={'result': {'text': '<script>window.hacked=true</script> 原始文稿', 'source': 'platform_subtitle'}})
                        for i in range(21)]
                rows = [r for r in rows if (status == 'all' or r['status'] == status) and query.get('search', [''])[0] in r['title']]
                number = int(query.get('page', ['1'])[0])
                return route.fulfill(json={'items': rows[(number-1)*20:number*20], 'total': len(rows), 'page': number})
            return route.fulfill(json=dict(ok=True))
        page.route('**/api/**', api)
        page.goto('http://127.0.0.1:8000/admin/history')
        expect(page.get_by_role('heading', name='提取记录', exact=True)).to_be_visible()
        expect(page.get_by_role('link', name='提取记录', exact=True)).to_be_visible()
        expect(page.get_by_role('navigation', name='列表分页')).to_contain_text('共 21 条')
        expect(page.get_by_text('用户邮箱 member0@example.com' if width < 768 else 'member0@example.com', exact=True).filter(visible=True).first).to_be_visible()
        expect(page.get_by_text('用户 ID', exact=True)).to_have_count(0)
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.get_by_role('button', name='查看 知识视频 20 记录')).to_be_visible()
        page.get_by_role('button', name='上一页', exact=True).click()
        page.get_by_role('button', name='查看 知识视频 00 记录').click()
        dialog = page.locator('dialog[open]')
        expect(dialog).to_contain_text('原始文稿')
        expect(dialog.get_by_role('link', name='打开原视频链接')).to_have_count(0)
        assert page.evaluate('window.hacked === undefined')
        dialog.get_by_role('button', name='关闭对话框').click()
        page.get_by_role('combobox', name='任务状态').select_option('done')
        expect(page.get_by_role('navigation', name='列表分页')).to_contain_text('共 11 条')
        page.get_by_role('textbox', name='搜索提取记录').fill('知识视频 20')
        page.get_by_role('button', name='搜索', exact=True).click()
        expect(page.get_by_role('navigation', name='列表分页')).to_contain_text('共 1 条')
        state['fail'] = True
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('暂时无法加载记录')
        state['fail'] = False
        page.get_by_role('button', name='重试', exact=True).click()
        expect(page.get_by_role('button', name='查看 知识视频 20 记录')).to_be_visible()
        page.get_by_role('textbox', name='搜索提取记录').fill('没有这个标题')
        page.get_by_role('button', name='搜索', exact=True).click()
        expect(page.get_by_text('暂无匹配的提取记录', exact=True)).to_be_visible()
        state['role'] = 'admin'
        page.goto('http://127.0.0.1:8000/admin/history')
        expect(page.get_by_role('button', name='查看 知识视频 00 记录')).to_be_visible()
        expect(page.get_by_role('button', name='删除', exact=True)).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        page.screenshot(path=str(SHOTS / f'history-{width}.png'))
        page.close()
        print(f'PASS admin history at {width}px')
    browser.close()
