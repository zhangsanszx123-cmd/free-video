"""Mocked desktop/mobile developer UI; Vite :5178, no real credentials or provider calls."""
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = os.getenv('UI_BASE_URL', 'http://127.0.0.1:5178')
SHOTS = Path(__file__).resolve().parents[2] / '.runtime' / 'open-api-ui'
SHOTS.mkdir(parents=True, exist_ok=True)
FAKE_TOKEN = 'fv_live_' + 'test-only-credential-never-real'.ljust(43, 'x')

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (1440, 390):
        context = browser.new_context(viewport={'width': width, 'height': 960})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        state = {'eligible': True, 'keys': [], 'create': 0}

        def route(r):
            path = r.request.url.split('/api/', 1)[-1]
            method = r.request.method
            if path == 'auth/me':
                return r.fulfill(json={'user': {'id': 1, 'email': 'tester@example.com', 'nickname': '开发者测试', 'created_at': '2026-11-28T00:00:00Z'}})
            if path == 'account/membership':
                return r.fulfill(json={'plan': 'monthly', 'name': '月卡会员', 'available_seconds': 36000, 'limit_seconds': 36000, 'used_seconds': 0, 'reserved_seconds': 0})
            if path == 'account/api-keys':
                if method == 'POST':
                    state['create'] += 1
                    key = {'id': 'test-id', 'name': r.request.post_data_json['name'], 'prefix': FAKE_TOKEN[:16], 'created_at': '2026-11-28T00:00:00Z', 'last_used_at': None, 'revoked_at': None}
                    state['keys'].insert(0, key)
                    return r.fulfill(status=201, json={'key': key, 'token': FAKE_TOKEN})
                return r.fulfill(json={'eligible': state['eligible'], 'max_keys': 3, 'keys': state['keys']})
            if path == 'account/api-keys/test-id' and method == 'DELETE':
                state['keys'][0]['revoked_at'] = '2026-11-28T01:00:00Z'
                return r.fulfill(json={'ok': True})
            return r.fulfill(json={})
        page.route(re.compile('^' + re.escape(BASE) + r'/api/'), route)
        page.goto(BASE + '/account/api')
        expect(page.get_by_role('heading', name='API 密钥', exact=True)).to_be_visible()
        page.get_by_label('密钥名称').fill('微信小程序')
        page.get_by_role('button', name='创建密钥', exact=True).click()
        expect(page.get_by_text(FAKE_TOKEN, exact=True)).to_be_visible()
        assert state['create'] == 1
        page.screenshot(path=str(SHOTS / f'keys-secret-{width}.png'), full_page=True)
        page.get_by_role('button', name='已保存，关闭展示').click()
        expect(page.get_by_text(FAKE_TOKEN, exact=True)).to_have_count(0)
        page.reload()
        expect(page.get_by_text('微信小程序', exact=True)).to_be_visible()
        expect(page.get_by_text(FAKE_TOKEN, exact=True)).to_have_count(0)
        page.get_by_role('button', name='撤销', exact=True).click()
        page.get_by_role('button', name='取消', exact=True).click()
        expect(page.get_by_role('button', name='确认撤销', exact=True)).to_have_count(0)
        page.get_by_role('button', name='撤销', exact=True).click()
        page.get_by_role('button', name='确认撤销', exact=True).click()
        expect(page.get_by_text('已撤销', exact=True)).to_be_visible()
        state['eligible'] = False
        page.reload()
        expect(page.get_by_text('当前账号暂不具备 API 创建权限', exact=False)).to_be_visible()
        expect(page.get_by_role('button', name='创建密钥', exact=True)).to_have_count(0)
        page.goto(BASE + '/account/api/docs')
        expect(page.get_by_role('heading', name='视频文案提取 API', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='视频与封面地址说明')).to_be_attached()
        assert page.get_by_role('link', name='下载 Python 示例').get_attribute('href') == '/examples/freevideo_open_api.py'
        assert page.locator('pre').first.inner_text().find('/api/open/v1') >= 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'document overflow at {width}'
        page.screenshot(path=str(SHOTS / f'docs-{width}.png'), full_page=True)
        assert not errors, errors
        context.close()
        print(f'PASS developer keys/docs {width}px')
    # Anonymous readers can open docs; key management prompts for login.
    page = browser.new_page()
    page.route(re.compile('^' + re.escape(BASE) + r'/api/'), lambda r: r.fulfill(json={'user': None}))
    page.goto(BASE + '/account/api/docs')
    expect(page.get_by_role('heading', name='视频文案提取 API', exact=True)).to_be_visible()
    page.goto(BASE + '/account/api')
    expect(page.get_by_role('dialog')).to_be_visible()
    print('PASS public docs and protected key management')
    browser.close()
