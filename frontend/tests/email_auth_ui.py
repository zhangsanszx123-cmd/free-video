"""Simplified two-field auth modal; Vite :5178, all APIs mocked."""
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright, expect

shots = Path('.runtime/simple-auth-ui')
shots.mkdir(parents=True, exist_ok=True)
backend = Path(__file__).resolve().parents[2] / 'backend'
image = subprocess.check_output([str(backend/'.venv/Scripts/python.exe'), '-c', "from app.captcha import _image; print(_image('6-4=?'))"], cwd=backend, text=True).strip()
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height in ((1440, 768), (1024, 600), (390, 844)):
        page = browser.new_page(viewport=dict(width=width, height=height))
        state = dict(user=None)
        requests, errors = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def api(route):
            path = route.request.url.split('/api/')[1].split('?')[0]
            requests.append(path)
            if path == 'auth/me': return route.fulfill(json=dict(user=state['user']))
            if path == 'auth/register':
                assert route.request.post_data_json == dict(email='tester@example.com', password='password 2026', captcha_id='test', captcha_answer='2')
                return route.fulfill(json=dict(verification_required=True, email='tester@example.com'))
            if path == 'auth/captcha': return route.fulfill(json=dict(id='test', image=image))
            if path == 'auth/login':
                assert route.request.post_data_json == dict(email='tester@example.com', password='password 2026')
                state['user'] = dict(id=1, email='tester@example.com', nickname='tester', username='u_test', created_at='2026-11-15T00:00:00Z')
                return route.fulfill(json=dict(user=state['user']))
            return route.fulfill(json=dict(ok=True, plans=[]))
        page.route('**/api/**', api)
        page.goto('http://127.0.0.1:5178/')
        if width <= 600: page.get_by_role('button', name='打开导航菜单').click()
        page.locator('nav').get_by_role('button', name='免费注册' if width <= 600 else '登录', exact=True).click()
        if width > 600:
            page.locator('dialog[open]').get_by_role('tab', name='注册', exact=True).click()
        dialog = page.locator('dialog[aria-labelledby="auth-title"]')
        expect(dialog.get_by_label('邮箱', exact=True)).to_be_visible()
        assert dialog.locator('input').count() == 3
        assert dialog.get_by_label('昵称（可选）').count() == 0
        assert dialog.get_by_label('确认密码').count() == 0
        expect(dialog.get_by_label('图形验证码', exact=True)).to_be_visible()
        dialog.get_by_label('图形验证码', exact=True).fill('9')
        dialog.get_by_role('button', name='刷新图形验证码').click()
        expect(dialog.get_by_label('图形验证码', exact=True)).to_have_value('')
        assert dialog.get_by_role('button', name='换一张').count() == 0
        assert dialog.evaluate('el => el.scrollHeight <= el.clientHeight + 1'), str(dialog.evaluate('el => ({scroll:el.scrollHeight, client:el.clientHeight, box:el.getBoundingClientRect().height})'))
        page.screenshot(path=str(shots/f'register-{width}.png'))
        dialog.get_by_label('邮箱', exact=True).fill('bad')
        dialog.get_by_label('密码', exact=True).fill('password 2026')
        dialog.get_by_role('button', name='注册账号').click()
        expect(dialog.get_by_text('请输入正确的邮箱地址')).to_be_visible()
        assert 'auth/register' not in requests
        dialog.get_by_label('邮箱', exact=True).fill('tester@example.com')
        dialog.get_by_label('图形验证码', exact=True).fill('2')
        dialog.get_by_role('button', name='注册账号').click()
        expect(dialog.get_by_role('status').filter(has_text='验证邮件已发送')).to_be_visible()
        assert state['user'] is None
        dialog.get_by_role('tab', name='登录', exact=True).click()
        expect(dialog.get_by_label('邮箱', exact=True)).to_be_visible()
        assert dialog.locator('input').count() == 2
        dialog.get_by_label('邮箱', exact=True).fill('tester@example.com')
        dialog.get_by_label('密码', exact=True).fill('password 2026')
        page.screenshot(path=str(shots/f'login-{width}.png'))
        dialog.get_by_role('button', name='登录', exact=True).click()
        expect(dialog).to_be_hidden()
        assert dialog.get_by_label('图形验证码', exact=True).count() == 0
        assert not errors, errors
        page.close()
        print(f'PASS simplified auth at {width}x{height}')
    browser.close()
